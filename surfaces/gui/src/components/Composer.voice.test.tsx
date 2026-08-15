import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./Composer";

const READY = {
  recording: false,
  model_installed: true,
  model_verified: true,
  test_passed: true,
  download_in_progress: false,
  model_name: "Whisper Large v3 Turbo (q5_0)",
  model_bytes: 574041195,
  installed_bytes: 574041195,
  download_total_bytes: 574041195,
  supported: true,
  device_summary: "Windows 11 / x64",
  compatibility_reason: null,
};
const NOT_READY = { ...READY, model_verified: false, test_passed: false };
const RECORDING = { ...READY, recording: true };

let invoke: ReturnType<typeof vi.fn>;

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gemma4:e4b",
  running: false,
  connected: true,
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  sessionId: "session-1",
  ...extra,
});

beforeEach(() => {
  invoke = vi.fn(async (cmd: string) => {
    if (cmd === "get_dictation_status") return READY;
    if (cmd === "start_dictation") return RECORDING;
    if (cmd === "stop_dictation") return "hello from local whisper";
    if (cmd === "cancel_dictation") return null;
    if (cmd === "dictation_level") return 0.6;
    return null;
  });
  (globalThis as any).__TAURI__ = { core: { invoke }, event: { listen: async () => () => {} } };
});

afterEach(() => {
  cleanup();
  delete (globalThis as any).__TAURI__;
});

describe("Composer voice input (whisper.cpp + CPAL)", () => {
  it("not ready mic button opens Settings voice section", async () => {
    invoke.mockImplementation(async (cmd: string) =>
      cmd === "get_dictation_status" ? NOT_READY : null,
    );
    const onConfigureVoiceInput = vi.fn();
    render(<Composer {...props({ onConfigureVoiceInput })} />);

    const mic = await screen.findByLabelText("Configure Voice Input in Settings");
    expect(mic.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(mic);
    await waitFor(() => expect(onConfigureVoiceInput).toHaveBeenCalled());
    expect(invoke).not.toHaveBeenCalledWith("start_dictation", undefined);
  });

  it("transitions READY -> LISTENING -> TRANSCRIBING -> READY with draft inserted", async () => {
    const onSend = vi.fn();
    render(<Composer {...props({ onSend })} />);

    const mic = await screen.findByLabelText("Start voice input");
    fireEvent.click(mic);

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith("start_dictation", undefined);
    });

    // In LISTENING state: live waveform and stop button appear
    const stopBtn = await screen.findByLabelText("Stop recording");
    expect(document.querySelector(".voice-wave")).toBeTruthy();
    expect(document.querySelector(".voice-timer")).toBeTruthy();

    // Clicking Stop triggers stop_dictation and inserts final transcript
    fireEvent.click(stopBtn);

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith("stop_dictation", undefined);
    });

    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toBe("hello from local whisper");
    });

    // Transcript is in prompt draft box, sending does not happen automatically
    expect(onSend).not.toHaveBeenCalled();

    // User can edit or click Send button
    const sendBtn = screen.getByLabelText("Send");
    fireEvent.click(sendBtn);
    expect(onSend).toHaveBeenCalledWith("hello from local whisper", [], undefined);
  });

  it("preserves pre-existing text in composer and appends transcript", async () => {
    render(<Composer {...props()} />);

    const initialTextarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    fireEvent.change(initialTextarea, { target: { value: "Review this code:" } });
    expect(initialTextarea.value).toBe("Review this code:");

    const mic = await screen.findByLabelText("Start voice input");
    fireEvent.click(mic);

    const stopBtn = await screen.findByLabelText("Stop recording");
    fireEvent.click(stopBtn);

    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toBe("Review this code: hello from local whisper");
    });
  });

  it("Escape key cancels recording and restores pre-recording draft text", async () => {
    render(<Composer {...props()} />);

    const textarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Draft to keep" } });

    const mic = await screen.findByLabelText("Start voice input");
    fireEvent.click(mic);

    await screen.findByLabelText("Stop recording");

    // Press Escape
    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith("cancel_dictation", undefined);
    });

    const restoredTextarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    expect(restoredTextarea.value).toBe("Draft to keep");
    await screen.findByLabelText("Start voice input");
  });

  it("Enter does not send while recording; Enter sends only when ready with draft", async () => {
    const onSend = vi.fn();
    render(<Composer {...props({ onSend })} />);

    const mic = await screen.findByLabelText("Start voice input");
    fireEvent.click(mic);

    await screen.findByLabelText("Stop recording");

    // Pressing enter while recording must be ignored
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();

    // Stop recording
    const stopBtn = screen.getByLabelText("Stop recording");
    fireEvent.click(stopBtn);

    await waitFor(() => {
      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toBe("hello from local whisper");
    });

    const activeTextarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    // Pressing Enter in READY state sends draft
    fireEvent.keyDown(activeTextarea, { key: "Enter", shiftKey: false });
    expect(onSend).toHaveBeenCalledWith("hello from local whisper", [], undefined);
  });

  it("preserves conversation LLM model selector and does not create voice model picker", async () => {
    render(<Composer {...props({ model: "gemma4:e4b", models: ["gemma4:e4b", "gpt-5"] })} />);

    // Model pill displays short model name "e4b"
    const modelPill = await screen.findByText("e4b");
    expect(modelPill).toBeTruthy();

    const mic = await screen.findByLabelText("Start voice input");
    fireEvent.click(mic);

    await screen.findByLabelText("Stop recording");

    const stopBtn = screen.getByLabelText("Stop recording");
    fireEvent.click(stopBtn);

    // Model remains unchanged after voice interaction
    await waitFor(() => {
      expect(screen.getByText("e4b")).toBeTruthy();
    });
  });
});
