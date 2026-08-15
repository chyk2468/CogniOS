/**
 * ==========================================================================
 * COGNIOS INTERACTIVE PRESENTATION — MODULAR JAVASCRIPT
 * ==========================================================================
 */

document.addEventListener('DOMContentLoaded', () => {
  initScrollProgress();
  initIntersectionObserver();
  initKeyboardNavigation();
  initArchitectureInspector();
  initTurnEngineLoop();
  initSimulationTimeline();
  initToolFilters();
  initMemorySimulator();
  initMultimodalTabs();
  initVoiceRecorderDemo();
  initMaturityFilters();
  initPitchModals();
  initCopyButtons();
});

/* --------------------------------------------------------------------------
   1. Scroll Progress Bar & Nav Links Spy
   -------------------------------------------------------------------------- */
function initScrollProgress() {
  const progressBar = document.getElementById('scroll-progress');
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav-links a');

  window.addEventListener('scroll', () => {
    const winScroll = document.documentElement.scrollTop;
    const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
    const scrolled = (winScroll / height) * 100;
    if (progressBar) {
      progressBar.style.width = scrolled + '%';
    }

    // Active nav link spy
    let currentId = '';
    sections.forEach(section => {
      const sectionTop = section.offsetTop - 120;
      const sectionHeight = section.offsetHeight;
      if (winScroll >= sectionTop && winScroll < sectionTop + sectionHeight) {
        currentId = section.getAttribute('id');
      }
    });

    navLinks.forEach(link => {
      link.classList.remove('active');
      if (link.getAttribute('href') === `#${currentId}`) {
        link.classList.add('active');
      }
    });
  });
}

/* --------------------------------------------------------------------------
   2. Intersection Observer for Scroll Animations
   -------------------------------------------------------------------------- */
function initIntersectionObserver() {
  const observerOptions = {
    threshold: 0.15,
    rootMargin: '0px 0px -50px 0px'
  };

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        obs.unobserve(entry.target);
      }
    });
  }, observerOptions);

  document.querySelectorAll('.reveal-on-scroll').forEach(el => {
    observer.observe(el);
  });
}

/* --------------------------------------------------------------------------
   3. Keyboard Navigation (1-9 Shortcuts, ESC Modal Dismiss)
   -------------------------------------------------------------------------- */
function initKeyboardNavigation() {
  const sectionMap = {
    '1': 'overview',
    '2': 'problem',
    '3': 'architecture',
    '4': 'turnengine',
    '5': 'tools',
    '6': 'security',
    '7': 'providers',
    '8': 'demo',
    '9': 'evidence'
  };

  document.addEventListener('keydown', (e) => {
    // Ignore keystrokes when typing inside inputs
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      return;
    }

    if (e.key === 'Escape') {
      closePitchDirect();
      return;
    }

    if (sectionMap[e.key]) {
      const target = document.getElementById(sectionMap[e.key]);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth' });
      }
    }
  });
}

/* --------------------------------------------------------------------------
   4. Architecture Layer Inspector
   -------------------------------------------------------------------------- */
const archSubsystems = {
  ui: {
    title: "Desktop Presentation Surface",
    path: "surfaces/gui/ (React 18 + Tauri v2)",
    resp: "Renders virtualized conversation timelines, live streaming tokens, interactive tool approval cards, thinking dropdowns, and waveform dictation buttons.",
    classes: [
      "App.tsx — Root coordinator & WebSocket event dispatcher",
      "Transcript.tsx — Virtualized message timeline with thinking panels",
      "Composer.tsx — Multimodal input bar with /skill autocompletion",
      "useVoiceInput.ts — React hook bridging UI to Tauri native STT"
    ],
    conns: "Connects to FastAPI over authenticated WebSockets (/ws/session/{id}) passing X-CogniOS-Token."
  },
  server: {
    title: "ASGI Control Plane & Session Manager",
    path: "cogniwork/server/app.py & manager.py",
    resp: "FastAPI server running on 127.0.0.1. Manages WebSocket message pumping, session lifecycle, atomic turn locks, token rate limiting, and durable inbox parking.",
    classes: [
      "app.py:ws_session — WebSocket session endpoint with CSWSH protection",
      "SessionManager.try_mark_running() — Atomic turn concurrency locking",
      "SessionManager.broadcast_session() — Real-time event fan-out",
      "InboxStore — Cross-session human-in-the-loop triage broker"
    ],
    conns: "Supervised as a child sidecar by Tauri; spawns and delegates turns to TurnEngine."
  },
  engine: {
    title: "TurnEngine Agent Core",
    path: "cogniwork/engine.py:TurnEngine",
    resp: "Orchestrates the multi-turn agent execution cycle, token streaming, tool call evaluation, approval interruption, and outbound payload preparation.",
    classes: [
      "TurnEngine._loop() — Main async agent evaluation loop",
      "TurnEngine._handle_tool_calls() — Risk-tiered tool dispatcher",
      "TurnEngine._outbound_messages() — System prompt assembler",
      "TurnEngine._compact_now() — Context window compaction trigger"
    ],
    conns: "Evaluates permissions via PermissionEngine, queries LLMs via ProviderRouter, and invokes ToolRegistry."
  },
  providers: {
    title: "Multi-Provider AI Routing Plane",
    path: "cogniwork/providers/ (18 Provider Descriptors)",
    resp: "Dispatches requests across native OpenAI Responses, Claude Messages API with prompt caching, Google GenAI SDK, Bedrock, Vertex AI, and local Ollama.",
    classes: [
      "ProviderRouter.stream() — Model prefix router",
      "AnthropicProvider — Native Claude streaming + cache_control",
      "OpenAIResponsesProvider — Native OpenAI Responses API (GPT-5.6 / o-series)",
      "matrix.py — Curated model matrix & token context limits"
    ],
    conns: "Invoked by TurnEngine._astream() inside dedicated worker threads."
  },
  tools: {
    title: "Tool & Integration Mesh",
    path: "cogniwork/tools/, connectors/, mcp/",
    resp: "Executes over 160 concrete tools: local sandboxed file operations, stateful bash/PowerShell shells, git status, safe web fetch, MCP servers, and 35+ SaaS connectors.",
    classes: [
      "ToolRegistry — Schema generation and tool registry",
      "LocalExecutor — Persistent shell subprocess execution with kill hooks",
      "AddressGuard — SSRF validator with DNS resolution pinning",
      "MCPClientSession — Model Context Protocol stdio & SSE client"
    ],
    conns: "Executed by TurnEngine following PermissionEngine approval evaluation."
  },
  memory: {
    title: "Storage & Context Persistence",
    path: "cogniwork/memory/ & conversations.py",
    resp: "Persists conversation transcripts into append-only JSONL files, session metadata and audit logs in SQLite, and credentials in encrypted profile stores.",
    classes: [
      "SQLiteMemoryStore — Scoped durable facts (global / workspace)",
      "ConversationStore — JSONL message logs + SQLite session index",
      "CompactionState — Non-destructive context window summary tracker",
      "SecretStore — OS-specific encrypted credential profiles"
    ],
    conns: "Injected into TurnEngine system prompts and loaded on session initialization."
  }
};

function selectArch(key) {
  const data = archSubsystems[key];
  if (!data) return;

  const titleEl = document.getElementById('drawer-title');
  const pathEl = document.getElementById('drawer-path');
  const respEl = document.getElementById('drawer-resp');
  const connsEl = document.getElementById('drawer-conns');
  const listEl = document.getElementById('drawer-classes');

  if (titleEl) titleEl.innerText = data.title;
  if (pathEl) pathEl.innerText = data.path;
  if (respEl) respEl.innerText = data.resp;
  if (connsEl) connsEl.innerText = data.conns;

  if (listEl) {
    listEl.innerHTML = '';
    data.classes.forEach(c => {
      const li = document.createElement('li');
      li.innerHTML = `<code>${c}</code>`;
      listEl.appendChild(li);
    });
  }

  document.querySelectorAll('.diagram-node, .diagram-mini-node').forEach(el => {
    el.classList.remove('selected');
  });
  if (window.event && window.event.currentTarget) {
    window.event.currentTarget.classList.add('selected');
  }
}
window.selectArch = selectArch;

function initArchitectureInspector() {
  // Default selection is engine
  const defaultNode = document.querySelector('.diagram-node[onclick*="engine"]');
  if (defaultNode) defaultNode.classList.add('selected');
}

/* --------------------------------------------------------------------------
   5. TurnEngine Step Loop Animation
   -------------------------------------------------------------------------- */
let currentLoopStep = 0;
let loopInterval = null;

function stepLoop() {
  const steps = document.querySelectorAll('.loop-step');
  if (!steps.length) return;
  steps.forEach(s => s.classList.remove('active-loop'));
  currentLoopStep = (currentLoopStep + 1) % steps.length;
  steps[currentLoopStep].classList.add('active-loop');
}
window.stepLoop = stepLoop;

function toggleLoopAuto() {
  const btn = document.getElementById('loop-auto-btn');
  if (loopInterval) {
    clearInterval(loopInterval);
    loopInterval = null;
    if (btn) btn.innerText = "Auto-Animate";
  } else {
    loopInterval = setInterval(stepLoop, 1100);
    if (btn) btn.innerText = "Pause Animation";
  }
}
window.toggleLoopAuto = toggleLoopAuto;

function initTurnEngineLoop() {
  const firstStep = document.querySelector('.loop-step[data-step="0"]');
  if (firstStep) firstStep.classList.add('active-loop');
}

/* --------------------------------------------------------------------------
   6. Visual Simulation Timeline
   -------------------------------------------------------------------------- */
let simInterval = null;
let currentSimStep = 0;

function playSimulation() {
  resetSimulation();
  const playBtn = document.getElementById('sim-play-btn');
  if (playBtn) playBtn.innerText = "Executing Workflow...";

  simInterval = setInterval(() => {
    currentSimStep++;
    const card = document.getElementById(`sc-${currentSimStep}`);
    if (card) {
      card.classList.add('active-sim');
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
      clearInterval(simInterval);
      simInterval = null;
      if (playBtn) playBtn.innerText = "Replay Simulation";
    }
  }, 650);
}
window.playSimulation = playSimulation;

function resetSimulation() {
  if (simInterval) {
    clearInterval(simInterval);
    simInterval = null;
  }
  currentSimStep = 0;
  document.querySelectorAll('.sim-card').forEach(c => c.classList.remove('active-sim'));
  const playBtn = document.getElementById('sim-play-btn');
  if (playBtn) playBtn.innerText = "Play Simulation";
}
window.resetSimulation = resetSimulation;

function initSimulationTimeline() {
  // First card active initially
  const first = document.getElementById('sc-1');
  if (first) first.classList.add('active-sim');
}

/* --------------------------------------------------------------------------
   7. Tool Constellation Filter
   -------------------------------------------------------------------------- */
function filterTools(category) {
  document.querySelectorAll('.tools-filter-bar .filter-btn').forEach(b => {
    b.classList.remove('active');
  });
  if (window.event && window.event.target) {
    window.event.target.classList.add('active');
  }

  const cards = document.querySelectorAll('.tool-card');
  let count = 0;
  cards.forEach(card => {
    if (category === 'all' || card.getAttribute('data-cat') === category) {
      card.style.display = 'block';
      count++;
    } else {
      card.style.display = 'none';
    }
  });

  const countBadge = document.getElementById('tool-count-badge');
  if (countBadge) {
    countBadge.innerText = `${count} Tools Shown`;
  }
}
window.filterTools = filterTools;

function initToolFilters() {
  // Tool filter bar init
}

/* --------------------------------------------------------------------------
   8. Interactive Memory Simulator (Progressive Disclosure)
   -------------------------------------------------------------------------- */
function initMemorySimulator() {
  const slider = document.getElementById('memory-chars-slider');
  const countDisplay = document.getElementById('memory-chars-count');
  const modeBadge = document.getElementById('memory-mode-badge');
  const memoryList = document.getElementById('simulated-memory-output');

  if (!slider || !countDisplay || !modeBadge || !memoryList) return;

  function updateMemoryState(chars) {
    countDisplay.innerText = `${chars.toLocaleString()} chars`;
    const threshold = 8000;

    if (chars <= threshold) {
      modeBadge.className = 'badge badge-online';
      modeBadge.innerText = 'FULL INJECTION MODE';
      memoryList.innerHTML = `
        <div style="color: var(--accent-emerald); margin-bottom: 0.5rem;">Known memories (from earlier sessions):</div>
        <div>• [#1] User prefers concise bullet points and TypeScript.</div>
        <div>• [#2] Deploy target is AWS us-east-1 production stack.</div>
        <div>• [#3] Use pytest for python test suites with -v flag.</div>
        <div>• [#4] Strict typing enabled across all frontend components.</div>
        <div>• [#5] Do not modify Alembic migrations without approval.</div>
      `;
    } else {
      modeBadge.className = 'badge badge-warning';
      modeBadge.innerText = 'INDEX MODE (> 8,000 chars)';
      memoryList.innerHTML = `
        <div style="color: var(--accent-amber); margin-bottom: 0.5rem;">Known memories (from earlier sessions):</div>
        <div>• [#45] Use pytest for python test suites with -v flag. (Newest #1 in full)</div>
        <div>• [#44] Strict typing enabled across all frontend components. (Newest #2 in full)</div>
        <div>• [#1] User coding style preferences... (One-line summary)</div>
        <div>• [#2] Deploy target infrastructure settings... (One-line summary)</div>
        <div style="color: var(--accent-cyan); margin-top: 0.5rem;"><em>(Some memories above show only a one-line summary. Call memory_read with [#id]s before acting.)</em></div>
      `;
    }
  }

  slider.addEventListener('input', (e) => {
    updateMemoryState(parseInt(e.target.value, 10));
  });

  updateMemoryState(3200);
}

/* --------------------------------------------------------------------------
   9. Multimodal Tabs & Voice Recorder Demo
   -------------------------------------------------------------------------- */
function switchTab(tabId) {
  document.querySelectorAll('.tabs-nav .tab-btn').forEach(b => {
    b.classList.remove('active');
  });
  if (window.event && window.event.target) {
    window.event.target.classList.add('active');
  }

  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.remove('active');
  });
  const activePane = document.getElementById(`tab-${tabId}`);
  if (activePane) {
    activePane.classList.add('active');
  }
}
window.switchTab = switchTab;

function initMultimodalTabs() {}

function initVoiceRecorderDemo() {
  const micBtn = document.getElementById('voice-sim-btn');
  const waveform = document.getElementById('voice-sim-waveform');
  const transcriptBox = document.getElementById('voice-sim-transcript');

  if (!micBtn || !waveform || !transcriptBox) return;

  let isRecording = false;

  micBtn.addEventListener('click', () => {
    if (!isRecording) {
      isRecording = true;
      micBtn.className = 'btn btn-primary animated-pulse-glow';
      micBtn.innerText = "🛑 Stop Dictation";
      waveform.classList.add('recording');
      transcriptBox.innerText = "Listening to local microphone (16 kHz mono CPAL stream)...";
    } else {
      isRecording = false;
      micBtn.className = 'btn btn-secondary';
      micBtn.innerText = "🎙️ Start Voice Dictation";
      waveform.classList.remove('recording');
      transcriptBox.innerHTML = `<strong>Local Whisper Transcript:</strong> "Refactor the test suite in tests/ and verify with pytest." <span class="badge badge-online">0ms Network Latency</span>`;
    }
  });
}

/* --------------------------------------------------------------------------
   10. Feature Maturity Matrix Filter
   -------------------------------------------------------------------------- */
function filterMaturity(status) {
  document.querySelectorAll('.maturity-filter-btn').forEach(b => b.classList.remove('active'));
  if (window.event && window.event.target) {
    window.event.target.classList.add('active');
  }

  const rows = document.querySelectorAll('.maturity-table tbody tr');
  rows.forEach(row => {
    const badge = row.querySelector('.badge');
    const badgeText = badge ? badge.innerText.toLowerCase() : '';
    if (status === 'all') {
      row.style.display = '';
    } else if (status === 'implemented' && badgeText.includes('production')) {
      row.style.display = '';
    } else if (status === 'partial' && badgeText.includes('partial')) {
      row.style.display = '';
    } else if (status === 'placeholder' && badgeText.includes('paused')) {
      row.style.display = '';
    } else {
      row.style.display = 'none';
    }
  });
}
window.filterMaturity = filterMaturity;

function initMaturityFilters() {}

/* --------------------------------------------------------------------------
   11. Accordion Toggles
   -------------------------------------------------------------------------- */
function toggleAccordion(headEl) {
  const item = headEl.parentElement;
  item.classList.toggle('open');
}
window.toggleAccordion = toggleAccordion;

/* --------------------------------------------------------------------------
   12. Pitch Modal Controller
   -------------------------------------------------------------------------- */
const pitchContent = {
  10: {
    title: "10-Second Pitch (Non-Technical)",
    text: "Most AI tools are just chat boxes in a browser tab that talk about work. CogniOS is an intelligent CogniWork agent installed on your desktop that actually does the work—editing files, organizing projects, drafting emails, updating calendars, and triaging your apps, all while keeping your data private on your own computer."
  },
  60: {
    title: "60-Second Pitch (Developer / Product)",
    text: "CogniOS transforms LLMs from passive text generators into active operating system actors. Built on a Tauri and FastAPI architecture, it runs an autonomous Python agent engine locally. CogniOS connects to your terminal, local git repos, MCP servers, and SaaS tools like Slack and GitHub. It features human-in-the-loop permission gating, offline Whisper dictation, and seamless model routing across OpenAI, Claude, Gemini, and local Ollama. Instead of copy-pasting code snippets, CogniOS implements changes, verifies test suites, and requests approval before taking high-risk actions."
  },
  300: {
    title: "5-Minute Pitch (Comprehensive Executive)",
    text: "Traditional AI assistants are passive conversational interfaces detached from your actual work environment. CogniOS is architected from the ground up as an AI operating system.\n\nIt features a native Rust and React desktop shell that supervises a local FastAPI agent daemon. The core TurnEngine drives multi-step problem-solving: running parallel low-risk reads, executing sandboxed file writes, and evaluating shell commands under human approval.\n\nCogniOS is completely model-agnostic, seamlessly routing across Claude, GPT-5.6, Gemini, Bedrock, Vertex, and local Ollama models with prompt caching and non-destructive context compaction. It includes offline Whisper voice transcription, SQLite-backed long-term memory, dynamic MCP client support, and 35+ SaaS connectors. It delivers finished, verified work safely, reliably, and locally."
  },
  tech: {
    title: "Senior Software Architect & Technical Deep Dive",
    text: "CogniOS is engineered around a clean separation between presentation, orchestration, and model invocation. The frontend is a high-performance React application inside a Tauri shell that communicates with a local FastAPI daemon over authenticated WebSockets.\n\nThe core runtime is TurnEngine, an asynchronous agent loop that evaluates tools iteratively. Unlike naive implementations, CogniOS categorizes tool calls by risk: read-only operations run concurrently via thread pools, while mutations execute serially. Every action passes through PermissionEngine, which enforces sandboxed multi-root directory boundaries, command whitelists, and approval gates. Suspended turns park in a durable SQLite inbox, surviving network disconnects and application restarts.\n\nOn the AI layer, CogniOS avoids vendor lock-in through ProviderRouter, supporting native OpenAI Responses, Claude Messages API with prompt caching, Google GenAI SDK, Bedrock, Vertex AI, and Ollama. When contexts approach token limits, non-destructive compaction summarizes older turns without altering the canonical JSONL log. Voice is handled completely offline via an embedded whisper.cpp engine in Rust. It's a complete, extensible, local-first operating layer for autonomous AI."
  }
};

function openPitch(type) {
  const p = pitchContent[type];
  if (!p) return;
  const titleEl = document.getElementById('modal-title');
  const bodyEl = document.getElementById('modal-body');
  const modal = document.getElementById('pitch-modal');

  if (titleEl) titleEl.innerText = p.title;
  if (bodyEl) bodyEl.innerText = p.text;
  if (modal) modal.classList.add('active');
}
window.openPitch = openPitch;

function closePitchDirect() {
  const modal = document.getElementById('pitch-modal');
  if (modal) modal.classList.remove('active');
}
window.closePitchDirect = closePitchDirect;

function closePitch(e) {
  if (e.target.id === 'pitch-modal') {
    closePitchDirect();
  }
}
window.closePitch = closePitch;

function initPitchModals() {}

/* --------------------------------------------------------------------------
   13. Copy Buttons with Animated Visual Feedback
   -------------------------------------------------------------------------- */
function initCopyButtons() {
  document.querySelectorAll('.copy-code-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const code = btn.getAttribute('data-code') || btn.innerText;
      navigator.clipboard.writeText(code).then(() => {
        const orig = btn.innerText;
        btn.innerText = "✓ Copied!";
        btn.style.color = "var(--accent-emerald)";
        setTimeout(() => {
          btn.innerText = orig;
          btn.style.color = "";
        }, 1800);
      });
    });
  });
}
