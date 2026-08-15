//! A local, offline speech-to-text engine.
//!
//! This crate deliberately has no Tauri, UI, clipboard, or global-shortcut dependency. Hosts
//! own their own UX and permission flows; they use [`Dictation`] for microphone capture,
//! model provisioning, and final transcription.

use std::{
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, Sender},
        Arc, Mutex,
    },
    thread,
    time::{SystemTime, UNIX_EPOCH},
};

use cpal::{
    traits::{DeviceTrait, HostTrait, StreamTrait},
    SampleFormat, Stream, StreamConfig,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

/// A fast, high-accuracy quantized Whisper model (~547 MB).
pub const DEFAULT_MODEL_FILE: &str = "ggml-large-v3-turbo-q5_0.bin";
pub const DEFAULT_MODEL_URL: &str =
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin";
pub const DEFAULT_MODEL_BYTES: u64 = 574_041_195;
pub const DEFAULT_MODEL_SHA256: &str =
    "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2";
const WHISPER_SAMPLE_RATE: u32 = 16_000;

#[derive(Debug, Clone, Serialize)]
pub struct DictationStatus {
    pub recording: bool,
    pub model_installed: bool,
    pub model_verified: bool,
    pub test_passed: bool,
    pub download_in_progress: bool,
    pub model_name: &'static str,
    pub model_bytes: u64,
    pub installed_bytes: u64,
    pub download_total_bytes: u64,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct DownloadProgress {
    pub downloaded_bytes: u64,
    pub total_bytes: u64,
}

struct Recording {
    stream: Stream,
    samples: Arc<Mutex<Vec<f32>>>,
    sample_rate: u32,
}

/// A reusable single-microphone dictation session manager.
///
/// It records only while a host has explicitly started a session; audio is held in memory for
/// that session and is never persisted. The downloaded recognition model is the only data kept
/// under `model_dir`.
pub struct Dictation {
    model_path: PathBuf,
    verified_marker_path: PathBuf,
    ready_marker_path: PathBuf,
    commands: Sender<Command>,
    recording: Arc<Mutex<bool>>,
    // Live handle onto the in-flight recording's sample buffer (set by the capture worker
    // for the duration of a session) so hosts can meter input loudness for UI feedback.
    live: Arc<Mutex<Option<(Arc<Mutex<Vec<f32>>>, u32)>>>,
    download_in_progress: AtomicBool,
    cancel_download: AtomicBool,
    cached_context: Mutex<Option<Arc<WhisperContext>>>,
}

enum Command {
    Start(Sender<Result<(), String>>),
    Stop(Sender<Result<RecordedAudio, String>>),
    Cancel(Sender<()>),
}

struct RecordedAudio {
    samples: Vec<f32>,
    sample_rate: u32,
}

impl Dictation {
    pub fn new(model_dir: impl Into<PathBuf>) -> Self {
        // CPAL's CoreAudio stream is intentionally !Send. Keep it on one dedicated owner thread
        // rather than unsafely forcing it through Tauri's Send + Sync application state.
        let (commands, receiver) = mpsc::channel();
        let recording = Arc::new(Mutex::new(false));
        let live = Arc::new(Mutex::new(None));
        let worker_recording = recording.clone();
        let worker_live = live.clone();
        thread::spawn(move || capture_worker(receiver, worker_recording, worker_live));
        let model_dir_path = model_dir.into();
        let model_path = model_dir_path.join(DEFAULT_MODEL_FILE);
        let verified_marker_path = model_path.with_extension("bin.verified");
        let ready_marker_path = model_path.with_extension("bin.ready");

        // If not present in user model directory, search candidate paths in priority order:
        // 1. Explicit environment variable override
        // 2. Bundled resource paths adjacent to current executable
        // 3. Crate / repository workspace paths
        if !model_path.is_file() {
            let mut candidates = Vec::new();
            if let Ok(override_path) = std::env::var("COGNIWORK_WHISPER_MODEL_PATH")
                .or_else(|_| std::env::var("COWORKER_WHISPER_MODEL_PATH"))
            {
                candidates.push(PathBuf::from(override_path));
            }
            if let Ok(exe) = std::env::current_exe() {
                if let Some(parent) = exe.parent() {
                    candidates.push(parent.join("models").join(DEFAULT_MODEL_FILE));
                    candidates.push(parent.join("resources").join("models").join(DEFAULT_MODEL_FILE));
                    if let Some(grandparent) = parent.parent() {
                        candidates.push(grandparent.join("Resources").join("models").join(DEFAULT_MODEL_FILE));
                    }
                }
            }
            let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            candidates.push(manifest_dir.join("whisper.cpp").join("models").join(DEFAULT_MODEL_FILE));
            candidates.push(manifest_dir.join("../stt/whisper.cpp/models").join(DEFAULT_MODEL_FILE));
            candidates.push(PathBuf::from("stt/whisper.cpp/models").join(DEFAULT_MODEL_FILE));
            candidates.push(PathBuf::from("openworker/stt/whisper.cpp/models").join(DEFAULT_MODEL_FILE));
            candidates.push(PathBuf::from("../../../stt/whisper.cpp/models").join(DEFAULT_MODEL_FILE));
            candidates.push(PathBuf::from("../../stt/whisper.cpp/models").join(DEFAULT_MODEL_FILE));
            candidates.push(PathBuf::from("../stt/whisper.cpp/models").join(DEFAULT_MODEL_FILE));

            for candidate in candidates {
                if candidate.is_file() {
                    if let Ok(meta) = fs::metadata(&candidate) {
                        if meta.len() == DEFAULT_MODEL_BYTES {
                            let _ = fs::create_dir_all(&model_dir_path);
                            if fs::copy(&candidate, &model_path).is_ok() {
                                let _ = write_verification_marker(&model_path, &verified_marker_path);
                                let _ = fs::write(&ready_marker_path, b"ready");
                                break;
                            }
                        }
                    }
                }
            }
        }

        Self {
            verified_marker_path,
            ready_marker_path,
            model_path,
            commands,
            recording,
            live,
            download_in_progress: AtomicBool::new(false),
            cancel_download: AtomicBool::new(false),
            cached_context: Mutex::new(None),
        }
    }

    pub fn status(&self) -> DictationStatus {
        let model_installed = self.model_path.is_file();
        let model_verified = model_installed
            && model_verification_marker_matches(&self.model_path, &self.verified_marker_path);
        let installed_bytes = if model_installed {
            fs::metadata(&self.model_path).map(|m| m.len()).unwrap_or(0)
        } else {
            0
        };
        DictationStatus {
            recording: self.recording.lock().map(|r| *r).unwrap_or(false),
            model_installed,
            model_verified,
            test_passed: model_verified && self.ready_marker_path.is_file(),
            download_in_progress: self.download_in_progress.load(Ordering::SeqCst),
            model_name: "Whisper Large v3 Turbo (q5_0)",
            model_bytes: if installed_bytes > 0 { installed_bytes } else { DEFAULT_MODEL_BYTES },
            installed_bytes,
            download_total_bytes: DEFAULT_MODEL_BYTES,
        }
    }

    pub fn model_path(&self) -> &Path {
        &self.model_path
    }

    /// Downloads the default model atomically. Hosts should call this only after an explicit
    /// user action because it is a sizeable download.
    pub fn install_default_model(&self) -> Result<(), String> {
        self.install_default_model_with_progress(|_| {})
    }

    /// Downloads and verifies the default model atomically, reporting byte progress to the host.
    /// A canceled/failed transfer never replaces a previously verified model.
    pub fn install_default_model_with_progress(
        &self,
        mut on_progress: impl FnMut(DownloadProgress),
    ) -> Result<(), String> {
        if self.status().model_verified {
            return Ok(());
        }
        if self
            .download_in_progress
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err("The local voice model is already downloading.".to_owned());
        }
        self.cancel_download.store(false, Ordering::SeqCst);

        let result = (|| {
            let parent = self
                .model_path
                .parent()
                .ok_or_else(|| "Could not determine the local model directory.".to_owned())?;
            fs::create_dir_all(parent)
                .map_err(|e| format!("Could not create model directory: {e}"))?;

            let partial = self.model_path.with_extension("bin.part");
            // Per-read timeout, not overall: a 142 MB transfer legitimately takes minutes, but
            // a stalled connection must surface as an error — the cancel flag is only observed
            // between reads, so an indefinitely blocked read would also make Cancel unresponsive.
            let agent = ureq::AgentBuilder::new()
                .timeout_connect(std::time::Duration::from_secs(30))
                .timeout_read(std::time::Duration::from_secs(30))
                .build();
            let response = agent
                .get(DEFAULT_MODEL_URL)
                .call()
                .map_err(|e| format!("Could not download the local voice model: {e}"))?;
            let mut input = response.into_reader();
            let mut output = fs::File::create(&partial)
                .map_err(|e| format!("Could not save the local voice model: {e}"))?;
            let mut downloaded = 0_u64;
            let mut last_reported = 0_u64;
            let mut buffer = [0_u8; 64 * 1024];
            on_progress(DownloadProgress {
                downloaded_bytes: 0,
                total_bytes: DEFAULT_MODEL_BYTES,
            });
            loop {
                if self.cancel_download.load(Ordering::SeqCst) {
                    drop(output);
                    let _ = fs::remove_file(&partial);
                    return Err("Voice model download canceled.".to_owned());
                }
                let count = input
                    .read(&mut buffer)
                    .map_err(|e| format!("Could not download the local voice model: {e}"))?;
                if count == 0 {
                    break;
                }
                output
                    .write_all(&buffer[..count])
                    .map_err(|e| format!("Could not save the local voice model: {e}"))?;
                downloaded += count as u64;
                if downloaded.saturating_sub(last_reported) >= 512 * 1024
                    || downloaded == DEFAULT_MODEL_BYTES
                {
                    last_reported = downloaded;
                    on_progress(DownloadProgress {
                        downloaded_bytes: downloaded,
                        total_bytes: DEFAULT_MODEL_BYTES,
                    });
                }
            }
            output
                .flush()
                .map_err(|e| format!("Could not finish saving the local voice model: {e}"))?;
            drop(output);

            verify_model_file(&partial)?;
            if self.model_path.exists() {
                fs::remove_file(&self.model_path)
                    .map_err(|e| format!("Could not replace the local voice model: {e}"))?;
            }
            fs::rename(&partial, &self.model_path)
                .map_err(|e| format!("Could not install the local voice model: {e}"))?;
            write_verification_marker(&self.model_path, &self.verified_marker_path)?;
            let _ = fs::remove_file(&self.ready_marker_path);
            on_progress(DownloadProgress {
                downloaded_bytes: DEFAULT_MODEL_BYTES,
                total_bytes: DEFAULT_MODEL_BYTES,
            });
            Ok(())
        })();

        self.download_in_progress.store(false, Ordering::SeqCst);
        self.cancel_download.store(false, Ordering::SeqCst);
        result
    }

    /// Verifies an already-installed model (including installs made by older app versions).
    pub fn verify_default_model(&self) -> Result<(), String> {
        verify_model_file(&self.model_path)?;
        write_verification_marker(&self.model_path, &self.verified_marker_path)
    }

    pub fn cancel_model_download(&self) {
        self.cancel_download.store(true, Ordering::SeqCst);
    }

    pub fn mark_test_passed(&self) -> Result<(), String> {
        if !self.status().model_verified {
            return Err("Verify the local voice model before testing it.".to_owned());
        }
        fs::write(&self.ready_marker_path, b"ready")
            .map_err(|e| format!("Could not save the voice input test result: {e}"))
    }

    pub fn delete_default_model(&self) -> Result<(), String> {
        self.cancel_model_download();
        self.cancel();
        if let Ok(mut guard) = self.cached_context.lock() {
            *guard = None;
        }
        for path in [
            self.model_path.clone(),
            self.model_path.with_extension("bin.part"),
            self.verified_marker_path.clone(),
            self.ready_marker_path.clone(),
        ] {
            if path.exists() {
                fs::remove_file(&path)
                    .map_err(|e| format!("Could not remove {}: {e}", path.display()))?;
            }
        }
        Ok(())
    }

    fn get_or_load_context(&self) -> Result<Arc<WhisperContext>, String> {
        let mut guard = self
            .cached_context
            .lock()
            .map_err(|e| format!("Could not access voice model cache: {e}"))?;
        if let Some(ctx) = guard.as_ref() {
            return Ok(ctx.clone());
        }
        if !self.model_path.is_file() {
            return Err("The local voice model is not installed yet.".to_owned());
        }
        let context = WhisperContext::new_with_params(
            self.model_path
                .to_str()
                .ok_or_else(|| "The local voice model path is not valid text.".to_owned())?,
            WhisperContextParameters::default(),
        )
        .map_err(|e| format!("Could not load the local voice model: {e}"))?;
        let arc = Arc::new(context);
        *guard = Some(arc.clone());
        Ok(arc)
    }

    /// Begins microphone capture. A host must call [`stop_and_transcribe`](Self::stop_and_transcribe)
    /// or [`cancel`](Self::cancel) before a new recording can start.
    pub fn start(&self) -> Result<(), String> {
        if !self.status().model_verified {
            return Err("Set up and verify Voice Input in Settings first.".to_owned());
        }
        let (reply, result) = mpsc::channel();
        self.commands
            .send(Command::Start(reply))
            .map_err(|_| "Dictation is unavailable because its audio worker stopped.".to_owned())?;
        result
            .recv()
            .map_err(|_| "Dictation is unavailable because its audio worker stopped.".to_owned())?
    }

    /// Stops capture and returns a final local transcript. This is intentionally synchronous so
    /// hosts can run it off their UI thread and decide how to present completion/error states.
    pub fn stop_and_transcribe(&self) -> Result<String, String> {
        let (reply, result) = mpsc::channel();
        self.commands
            .send(Command::Stop(reply))
            .map_err(|_| "Dictation is unavailable because its audio worker stopped.".to_owned())?;
        let RecordedAudio {
            samples,
            sample_rate,
        } = result.recv().map_err(|_| {
            "Dictation is unavailable because its audio worker stopped.".to_owned()
        })??;
        if samples.len() < (sample_rate as usize / 4) {
            return Ok(String::new());
        }
        let resampled = resample_mono(&samples, sample_rate);
        match self.get_or_load_context() {
            Ok(ctx) => match transcribe_with_context(&ctx, &resampled) {
                Ok(text) => Ok(text),
                Err(_) => transcribe_with_cli_fallback(&self.model_path, &resampled),
            },
            Err(_) => transcribe_with_cli_fallback(&self.model_path, &resampled),
        }
    }

    /// Instantaneous input loudness of the in-flight recording, 0.0..=1.0 — RMS over the
    /// most recent ~100ms, scaled so conversational speech spans most of the range. 0.0
    /// while not recording. Cheap enough to poll at UI frame-ish rates.
    pub fn input_level(&self) -> f32 {
        let live = match self.live.lock() {
            Ok(guard) => guard,
            Err(_) => return 0.0,
        };
        let Some((samples, sample_rate)) = live.as_ref() else {
            return 0.0;
        };
        let Ok(samples) = samples.lock() else {
            return 0.0;
        };
        let window = (*sample_rate as usize / 10).max(1);
        let tail = &samples[samples.len().saturating_sub(window)..];
        if tail.is_empty() {
            return 0.0;
        }
        let mean_square: f32 = tail.iter().map(|s| s * s).sum::<f32>() / tail.len() as f32;
        (mean_square.sqrt() * 8.0).clamp(0.0, 1.0)
    }

    /// Returns a best-effort transcript of the in-flight recording without stopping capture.
    /// This uses the same local model as final dictation and snapshots the current in-memory
    /// audio so hosts can show live text while keeping the final transcript authoritative.
    pub fn partial_transcript(&self) -> Result<String, String> {
        if !self.status().recording {
            return Ok(String::new());
        }
        let (samples, sample_rate) = {
            let live = self
                .live
                .lock()
                .map_err(|_| "Could not read the active recording.".to_owned())?;
            let Some((samples, sample_rate)) = live.as_ref() else {
                return Ok(String::new());
            };
            let samples = samples
                .lock()
                .map_err(|_| "Could not read the active recording.".to_owned())?
                .clone();
            (samples, *sample_rate)
        };
        if samples.len() < (sample_rate as usize / 2) {
            return Ok(String::new());
        }
        let ctx = self.get_or_load_context()?;
        transcribe_with_context(&ctx, &resample_mono(&samples, sample_rate))
    }

    /// Discards the current in-memory recording without retaining or transcribing it.
    pub fn cancel(&self) {
        let (reply, done) = mpsc::channel();
        if self.commands.send(Command::Cancel(reply)).is_ok() {
            let _ = done.recv();
        }
    }
}

fn verify_model_file(path: &Path) -> Result<(), String> {
    let metadata =
        fs::metadata(path).map_err(|e| format!("Could not read the local voice model: {e}"))?;
    if metadata.len() != DEFAULT_MODEL_BYTES {
        return Err(format!(
            "The local voice model is incomplete ({} of {} bytes).",
            metadata.len(),
            DEFAULT_MODEL_BYTES
        ));
    }
    let mut file =
        fs::File::open(path).map_err(|e| format!("Could not read the local voice model: {e}"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|e| format!("Could not verify the local voice model: {e}"))?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    let actual = format!("{:x}", hasher.finalize());
    if actual != DEFAULT_MODEL_SHA256 {
        return Err(
            "The local voice model failed its checksum. Repair the download in Settings."
                .to_owned(),
        );
    }
    Ok(())
}

fn model_modified_millis(path: &Path) -> Option<u128> {
    fs::metadata(path)
        .ok()?
        .modified()
        .ok()?
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_millis())
}

fn write_verification_marker(model_path: &Path, marker_path: &Path) -> Result<(), String> {
    let modified = model_modified_millis(model_path)
        .ok_or_else(|| "Could not read the installed voice model timestamp.".to_owned())?;
    fs::write(marker_path, format!("{DEFAULT_MODEL_SHA256}\n{modified}\n"))
        .map_err(|e| format!("Could not record voice model verification: {e}"))
}

fn model_verification_marker_matches(model_path: &Path, marker_path: &Path) -> bool {
    let Ok(metadata) = fs::metadata(model_path) else {
        return false;
    };
    if metadata.len() != DEFAULT_MODEL_BYTES {
        return false;
    }
    let Ok(marker) = fs::read_to_string(marker_path) else {
        return false;
    };
    let mut lines = marker.lines();
    let hash_matches = lines.next() == Some(DEFAULT_MODEL_SHA256);
    let marker_modified = lines.next().and_then(|value| value.parse::<u128>().ok());
    hash_matches && marker_modified == model_modified_millis(model_path)
}

fn capture_worker(
    receiver: Receiver<Command>,
    recording_status: Arc<Mutex<bool>>,
    live: Arc<Mutex<Option<(Arc<Mutex<Vec<f32>>>, u32)>>>,
) {
    let mut recording: Option<Recording> = None;
    let set_live = |value: Option<(Arc<Mutex<Vec<f32>>>, u32)>| {
        if let Ok(mut guard) = live.lock() {
            *guard = value;
        }
    };
    for command in receiver {
        match command {
            Command::Start(reply) => {
                if recording.is_some() {
                    let _ = reply.send(Err("Dictation is already recording.".to_owned()));
                    continue;
                }
                match start_recording() {
                    Ok(next) => {
                        set_live(Some((next.samples.clone(), next.sample_rate)));
                        recording = Some(next);
                        if let Ok(mut active) = recording_status.lock() {
                            *active = true;
                        }
                        let _ = reply.send(Ok(()));
                    }
                    Err(error) => {
                        let _ = reply.send(Err(error));
                    }
                }
            }
            Command::Stop(reply) => {
                set_live(None);
                let result = recording
                    .take()
                    .ok_or_else(|| "Dictation is not recording.".to_owned())
                    .and_then(finish_recording);
                if let Ok(mut active) = recording_status.lock() {
                    *active = false;
                }
                let _ = reply.send(result);
            }
            Command::Cancel(reply) => {
                set_live(None);
                recording.take();
                if let Ok(mut active) = recording_status.lock() {
                    *active = false;
                }
                let _ = reply.send(());
            }
        }
    }
}

fn start_recording() -> Result<Recording, String> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or_else(|| "No microphone is available. Check your Mac sound settings.".to_owned())?;
    let supported = device
        .default_input_config()
        .map_err(|e| format!("Could not open the microphone: {e}"))?;
    let config: StreamConfig = supported.clone().into();
    let samples = Arc::new(Mutex::new(Vec::new()));
    let stream = build_stream(&device, &config, supported.sample_format(), samples.clone())?;
    stream
        .play()
        .map_err(|e| format!("Could not start microphone recording: {e}"))?;
    Ok(Recording {
        stream,
        samples,
        sample_rate: config.sample_rate.0,
    })
}

fn finish_recording(recording: Recording) -> Result<RecordedAudio, String> {
    let Recording {
        stream,
        samples,
        sample_rate,
    } = recording;
    drop(stream);
    let samples = samples
        .lock()
        .map_err(|_| "Could not read the recorded audio.".to_owned())?
        .clone();
    Ok(RecordedAudio {
        samples,
        sample_rate,
    })
}

fn build_stream(
    device: &cpal::Device,
    config: &StreamConfig,
    sample_format: SampleFormat,
    samples: Arc<Mutex<Vec<f32>>>,
) -> Result<Stream, String> {
    let channels = config.channels as usize;
    let on_error = |error| eprintln!("[ocw-stt] microphone stream error: {error}");
    match sample_format {
        SampleFormat::F32 => device
            .build_input_stream(
                config,
                move |data: &[f32], _| append_frames(&samples, data, channels, |sample| sample),
                on_error,
                None,
            )
            .map_err(|e| format!("Could not create microphone stream: {e}")),
        SampleFormat::I16 => device
            .build_input_stream(
                config,
                move |data: &[i16], _| {
                    append_frames(&samples, data, channels, |sample| {
                        sample as f32 / i16::MAX as f32
                    })
                },
                on_error,
                None,
            )
            .map_err(|e| format!("Could not create microphone stream: {e}")),
        SampleFormat::U16 => device
            .build_input_stream(
                config,
                move |data: &[u16], _| {
                    append_frames(&samples, data, channels, |sample| {
                        (sample as f32 / u16::MAX as f32) * 2.0 - 1.0
                    })
                },
                on_error,
                None,
            )
            .map_err(|e| format!("Could not create microphone stream: {e}")),
        other => Err(format!("Unsupported microphone sample format: {other:?}")),
    }
}

fn append_frames<T>(
    target: &Arc<Mutex<Vec<f32>>>,
    data: &[T],
    channels: usize,
    convert: impl Fn(T) -> f32,
) where
    T: Copy,
{
    let Ok(mut output) = target.lock() else {
        return;
    };
    output.reserve(data.len() / channels.max(1));
    for frame in data.chunks(channels.max(1)) {
        let sum: f32 = frame.iter().copied().map(&convert).sum();
        output.push(sum / frame.len() as f32);
    }
}

fn resample_mono(input: &[f32], source_rate: u32) -> Vec<f32> {
    if source_rate == WHISPER_SAMPLE_RATE {
        return input.to_vec();
    }
    let output_len =
        (input.len() as u64 * WHISPER_SAMPLE_RATE as u64 / source_rate as u64) as usize;
    let ratio = source_rate as f64 / WHISPER_SAMPLE_RATE as f64;
    (0..output_len)
        .map(|i| {
            let position = i as f64 * ratio;
            let left = position.floor() as usize;
            let right = (left + 1).min(input.len().saturating_sub(1));
            let fraction = (position - left as f64) as f32;
            input[left] * (1.0 - fraction) + input[right] * fraction
        })
        .collect()
}

fn transcribe_with_context(context: &WhisperContext, samples: &[f32]) -> Result<String, String> {
    let mut state = context
        .create_state()
        .map_err(|e| format!("Could not prepare transcription: {e}"))?;
    let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
    params.set_language(Some("en"));
    params.set_translate(false);
    params.set_print_progress(false);
    params.set_print_special(false);
    params.set_print_realtime(false);
    params.set_suppress_blank(true);
    state
        .full(params, samples)
        .map_err(|e| format!("Could not transcribe the recording: {e}"))?;

    let mut text = String::new();
    for segment in state.as_iter() {
        let segment = segment
            .to_str()
            .map_err(|e| format!("Could not read the transcript: {e}"))?;
        text.push_str(segment);
    }
    Ok(text.trim().to_owned())
}

fn write_wav_file(path: &Path, samples: &[f32], sample_rate: u32) -> std::io::Result<()> {
    let mut file = fs::File::create(path)?;
    let num_channels: u16 = 1;
    let bits_per_sample: u16 = 16;
    let byte_rate = sample_rate * u32::from(num_channels) * u32::from(bits_per_sample) / 8;
    let block_align = num_channels * bits_per_sample / 8;
    let data_len = (samples.len() * 2) as u32;
    let chunk_size = 36 + data_len;

    file.write_all(b"RIFF")?;
    file.write_all(&chunk_size.to_le_bytes())?;
    file.write_all(b"WAVE")?;
    file.write_all(b"fmt ")?;
    file.write_all(&16u32.to_le_bytes())?;
    file.write_all(&1u16.to_le_bytes())?;
    file.write_all(&num_channels.to_le_bytes())?;
    file.write_all(&sample_rate.to_le_bytes())?;
    file.write_all(&byte_rate.to_le_bytes())?;
    file.write_all(&block_align.to_le_bytes())?;
    file.write_all(&bits_per_sample.to_le_bytes())?;
    file.write_all(b"data")?;
    file.write_all(&data_len.to_le_bytes())?;

    for &sample in samples {
        let clamped = sample.max(-1.0).min(1.0);
        let val = if clamped < 0.0 {
            (clamped * 32768.0) as i16
        } else {
            (clamped * 32767.0) as i16
        };
        file.write_all(&val.to_le_bytes())?;
    }
    file.flush()?;
    Ok(())
}

fn transcribe_with_cli_fallback(model_path: &Path, samples: &[f32]) -> Result<String, String> {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let temp_wav = std::env::temp_dir().join(format!("ocw-voice-{unique}.wav"));
    write_wav_file(&temp_wav, samples, 16_000)
        .map_err(|e| format!("Could not save audio buffer: {e}"))?;

    let cli_candidates = [
        PathBuf::from("stt/whisper.cpp/build/bin/whisper-cli.exe"),
        PathBuf::from("stt/whisper.cpp/build/bin/whisper-cli"),
        PathBuf::from("stt/whisper.cpp/build/bin/main.exe"),
        PathBuf::from("stt/whisper.cpp/build/bin/main"),
    ];

    let cli_bin = cli_candidates
        .into_iter()
        .find(|p| p.is_file())
        .ok_or_else(|| "Local whisper-cli executable not found.".to_string())?;

    let output = std::process::Command::new(&cli_bin)
        .arg("-m")
        .arg(model_path)
        .arg("-f")
        .arg(&temp_wav)
        .arg("-nt")
        .arg("-np")
        .output()
        .map_err(|e| format!("Failed to run whisper-cli: {e}"))?;

    let _ = fs::remove_file(&temp_wav);

    let raw = String::from_utf8_lossy(&output.stdout);
    let mut lines = Vec::new();
    for line in raw.lines() {
        let trimmed = line.trim();
        if !trimmed.is_empty()
            && !trimmed.starts_with("read_audio_data:")
            && !trimmed.starts_with("whisper_")
            && !trimmed.starts_with("main:")
            && !trimmed.starts_with("system_info:")
        {
            lines.push(trimmed);
        }
    }
    Ok(lines.join(" ").trim().to_string())
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::{
        resample_mono, write_verification_marker, Dictation, DEFAULT_MODEL_BYTES,
        DEFAULT_MODEL_FILE,
    };

    #[test]
    fn resampling_preserves_a_16khz_stream() {
        let input = vec![0.0, 0.5, -0.5];
        assert_eq!(resample_mono(&input, 16_000), input);
    }

    #[test]
    fn resampling_converts_duration() {
        let input = vec![0.0; 48_000];
        assert_eq!(resample_mono(&input, 48_000).len(), 16_000);
    }

    #[test]
    fn default_model_size_matches_the_published_artifact() {
        assert_eq!(DEFAULT_MODEL_BYTES, 574_041_195);
    }

    #[test]
    fn readiness_requires_a_verified_model_and_persists_after_a_test() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("ocw-stt-readiness-{unique}"));
        fs::create_dir_all(&dir).unwrap();
        let model = dir.join(DEFAULT_MODEL_FILE);
        fs::File::create(&model)
            .unwrap()
            .set_len(DEFAULT_MODEL_BYTES)
            .unwrap();
        let dictation = Dictation::new(&dir);
        assert!(!dictation.status().model_verified);
        assert_eq!(dictation.status().installed_bytes, DEFAULT_MODEL_BYTES);
        write_verification_marker(&model, &dictation.verified_marker_path).unwrap();
        assert!(dictation.status().model_verified);
        assert!(!dictation.status().test_passed);
        dictation.mark_test_passed().unwrap();
        assert!(dictation.status().test_passed);
        dictation.delete_default_model().unwrap();
        assert!(!dictation.status().model_installed);
        assert_eq!(dictation.status().installed_bytes, 0);
        drop(dictation);
        fs::remove_dir_all(dir).unwrap();
    }
}
