# 🎙️ Saturday — Autonomous Local-First Windows AI Desktop Assistant

<p align="center">
  <img src="assets/icon.png" alt="Saturday Logo" width="120" onerror="this.style.display='none'"/>
</p>

<p align="center">
  <strong>An ultra-fast, local-first AI copilot for Windows with real-time voice streaming, local LLM reasoning, a robust trust & safety layer, and native Windows automation.</strong>
</p>

<p align="center">
  <a href="#-key-features"><img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white" alt="Windows Platform" /></a>
  <a href="#-installation-guide"><img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white" alt="Python Version" /></a>
  <a href="#-architecture"><img src="https://img.shields.io/badge/UI-PySide6%20Qt-41CD52?logo=qt&logoColor=white" alt="PySide6 UI" /></a>
  <a href="#-streaming-voice-pipeline"><img src="https://img.shields.io/badge/STT-Faster--Whisper-FF6F00" alt="Faster-Whisper" /></a>
  <a href="#-long-term-memory--reminders"><img src="https://img.shields.io/badge/Memory-ChromaDB-blueviolet" alt="ChromaDB" /></a>
  <a href="#-running-tests"><img src="https://img.shields.io/badge/Tests-29%2F29%20Passing-success" alt="Tests" /></a>
</p>

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
  - [Streaming Voice Pipeline](#-streaming-voice-pipeline)
  - [Trust & Safety Layer](#-trust--safety-layer)
  - [Intelligent Windows & Settings Resolver](#-intelligent-windows--settings-resolver)
  - [Windows Media & System Controls](#-windows-media--system-controls)
  - [Multi-Site & Deep Web Search](#-multi-site--deep-web-search)
  - [Long-Term Memory & Natural Language Reminders](#-long-term-memory--natural-language-reminders)
  - [Glassmorphism Command Bar UI](#-glassmorphism-command-bar-ui)
- [System Requirements](#-system-requirements)
- [Installation Guide](#-installation-guide)
  - [Method 1: Automated Installer (Recommended)](#method-1-automated-installer-recommended)
  - [Method 2: Manual PowerShell Setup](#method-2-manual-powershell-setup)
  - [Optional: Local Ollama LLM Setup](#optional-local-ollama-llm-setup)
- [Quick Start & Global Shortcuts](#-quick-start--global-shortcuts)
- [Example Voice Commands](#-example-voice-commands)
- [Project Architecture](#-project-architecture)
- [Configuration](#-configuration)
- [Running Tests](#-running-tests)
- [License](#-license)

---

## 🌟 Overview

**Saturday** is an autonomous desktop companion built from the ground up for Windows. Unlike cloud-dependent voice assistants that impose high latency and privacy tradeoffs, Saturday operates **entirely local-first**:

- ⚡ **Sub-Second Response Times**: Fast rule-based semantic priority matching (<10ms) with seamless fallback to warm local LLMs (Ollama / Qwen / Llama).
- 🔒 **Privacy by Design**: Voice transcription (Faster-Whisper), memory storage (ChromaDB), and system execution stay strictly on your local PC.
- 🛡️ **Guaranteed Reliability**: Built on a centralized **Trust Layer** where every action is either executed correctly, confirmed explicitly before destruction, or explained transparently.

---

## 🚀 Key Features

### 🎙️ Streaming Voice Pipeline
- **WebRTC VAD**: Real-time Voice Activity Detection with automatic silence detection and RMS ambient noise calibration.
- **Faster-Whisper STT**: Quantized local speech-to-text with microphone auto-probing and multi-rate audio streaming (48 kHz to 16 kHz resampler).
- **Native SAPI5 TTS**: Zero-latency Windows speech engine with instant interruptibility on `Esc` or new hotkey toggle.

### 🛡️ Trust & Safety Layer
- **Centralized `@safe_handler`**: Structurally prevents unhandled exceptions, raw tracebacks, or silent swallows.
- **Canonical `IntentResult`**: Every action resolves to `SUCCESS`, `NEEDS_CONFIRMATION`, `NEEDS_CLARIFICATION`, or `FAILED`.
- **Destructive Action Policy**: Irreversible commands (`delete_file`, `shutdown`, `restart`, `delete_folder`) pause and require explicit verbal or text confirmation (`yes` / `confirm`) before executing.

### ⚙️ Intelligent Windows & Settings Resolver
- **Windows Settings Protocol Routing (`ms-settings:`)**: Direct access to subpages:
  - *Mouse & Touchpad*: `"open mouse settings"` → `ms-settings:mousetouchpad`
  - *Sound & Volume*: `"open sound settings"` → `ms-settings:sound`
  - *Display & Night Light*: `"open display settings"` → `ms-settings:display`
  - *Network & Wi-Fi*: `"open wifi settings"` → `ms-settings:network-wifi`
  - *Windows Update*: `"open windows update"` → `ms-settings:windowsupdate`
  - *Privacy*: Camera, microphone, and location permissions.
- **Windows Admin & Management Applets**: Direct access to `devmgmt.msc`, `diskmgmt.msc`, `services.msc`, `taskmgr.exe`, `ncpa.cpl`, `control.exe`.
- **Special Folders**: Instant Explorer routing for `Documents`, `Downloads`, `Pictures`, `Videos`, `Desktop`.
- **Smart Disambiguation**: Intelligently handles dual-target entities (e.g. *Claude desktop app* vs. *Claude website*), remembering your preference.

### 🎵 Windows Media & System Controls
- **Global Hardware Media Keys**: Directly controls playback in any running media player (Spotify, YouTube in Chrome/Edge, VLC, Apple Music) using `VK_MEDIA_PLAY_PAUSE`, `VK_MEDIA_NEXT_TRACK`, `VK_MEDIA_PREV_TRACK`, and `VK_MEDIA_STOP`.
- **Direct Track & Video Streaming**: `"play Bohemian Rhapsody on Spotify"`, `"start a video of coding music"`, or `"put on some lo-fi beats"`.
- **System Actions**: Master volume adjustments, mute/unmute, screenshot capture (`Pictures\Saturday Screenshots`), workstation locking (`LockWorkStation`).

### 🔍 Multi-Site & Deep Web Search
- **Platform-Specific Search**: Native search URL generation for **YouTube, GitHub, Reddit, Amazon, Wikipedia, Stack Overflow, X/Twitter, Spotify, Netflix, IMDb, eBay, Google, Bing, DuckDuckGo**.
- **Dynamic Site Search**: Natural querying like `"search shoes on nike"` automatically maps to `site:nike.com`.

### 🧠 Long-Term Memory & Natural Language Reminders
- **ChromaDB Vector Store**: Semantic recall of personal facts, notes, credentials, and learned preferences.
- **APScheduler Engine**: Persistent background reminder system supporting relative and absolute expressions (`"in 20 mins"`, `"tomorrow at 3pm"`), with voice output, notifications, and HUD cards.

### 🖥️ Glassmorphism Command Bar UI
- **PyQt6 / PySide6 HUD**: Frameless, translucent dark-mode command bar with dynamic acrylic glass blur.
- **Real-Time Visualizer**: Audio waveform animation showing live microphone input levels.

---

## 💻 System Requirements

- **Operating System**: Windows 10 (64-bit) or Windows 11 (64-bit)
- **Python**: Python `3.10`, `3.11`, or `3.12`
- **Audio**: Working microphone & speakers / headphones
- **Hardware (Optional)**: NVIDIA GPU with CUDA support for accelerated Whisper STT (CPU inference works out-of-the-box).

---

## 📦 Installation Guide

### Method 1: Automated Installer (Recommended)

1. Clone the repository:
   ```cmd
   git clone https://github.com/saiyedarsh-hello/Sat.git
   cd Sat
   ```
2. Run the automated installer batch script:
   ```cmd
   install.bat
   ```
3. Launch Saturday:
   ```cmd
   python main.py
   ```

---

### Method 2: Manual PowerShell Setup

1. **Clone the Repository**:
   ```powershell
   git clone https://github.com/saiyedarsh-hello/Sat.git
   cd Sat
   ```

2. **Create and Activate a Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
   *(If script execution is restricted, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first).*

3. **Install Dependencies**:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Launch Saturday**:
   ```powershell
   python main.py
   ```

---

### 🤖 Optional: Local Ollama LLM Setup

Saturday includes a rule-based engine and can connect seamlessly to a local [Ollama](https://ollama.com) instance for offline AI conversational intelligence:

1. Download and install **[Ollama for Windows](https://ollama.com/download)**.
2. Pull a recommended model (e.g. `qwen2.5:7b` or `llama3.2:3b`):
   ```powershell
   ollama run qwen2.5:7b
   ```
3. Saturday will automatically detect the warm Ollama instance at startup!

---

## ⌨️ Quick Start & Global Shortcuts

| Shortcut | Action | Description |
|---|---|---|
| <kbd>Ctrl</kbd> + <kbd>Space</kbd> | **Voice Mode** | Activates real-time voice streaming and speech listening. |
| <kbd>Alt</kbd> + <kbd>Space</kbd> | **Command Bar** | Toggles the HUD search bar for typed commands and queries. |
| <kbd>Esc</kbd> | **Interrupt / Stop** | Instantly stops Saturday from speaking (TTS) and resets active task. |

---

## 🗣️ Example Voice Commands

```
# Media & Entertainment
"Play music"
"Pause the song"
"Start a video of space documentaries"
"Play Bohemian Rhapsody on Spotify"
"Put on some lo-fi beats"

# Deep Web & Site Search
"Search python tutorials on GitHub"
"Look up mechanical keyboards on Reddit"
"Search running shoes on Amazon"
"Search quantum computing on Wikipedia"

# Windows Settings & Administration
"Open mouse settings"
"Open display settings"
"Open Wi-Fi settings"
"Open Windows Update"
"Open Device Manager"
"Open Task Manager"

# System Controls
"Volume up" / "Volume down" / "Mute audio"
"Take a screenshot"
"Lock my computer"
"Shut down my PC"  (requires confirmation)

# Memory & Reminders
"Remember that my wifi password is secret"
"What is my wifi password?"
"Remind me in 25 minutes to check the oven"
"Show my reminders"

# File Operations
"Create a file called notes.txt"
"Delete my temp file"  (requires confirmation)
"Open my downloads folder"
```

---

## 🏗️ Project Architecture

```
Saturday/
├── ai/
│   ├── agent.py               # Top-level Goal -> Plan -> Execute agent loop
│   ├── intent_parser.py       # Multi-tiered intent classifier & slot extractor
│   ├── intent_result.py       # Canonical IntentResult states & @safe_handler decorator
│   └── llm_client.py          # Multi-backend LLM client (Ollama / OpenAI / Rules)
├── automation/
│   ├── app_control.py         # Native app launcher & process controller
│   ├── browser_control.py     # Browser selector & multi-site search engine
│   ├── file_ops.py            # File & folder manager with Recycle Bin safety
│   ├── reminder_engine.py     # APScheduler background reminder scheduler
│   ├── resolver.py            # Smart Windows settings, folders & app resolver
│   └── system_actions.py      # Windows media keys, volume, brightness & system hooks
├── config/
│   ├── config.py              # Dynamic configuration manager
│   └── config.json            # User preferences & persistent settings
├── core/
│   ├── app_controller.py      # Main Qt state machine & signal dispatcher
│   └── states.py              # State definitions (IDLE, LISTENING, PROCESSING, SPEAKING)
├── database/
│   ├── db.py                  # SQLite storage for persistent tasks and reminders
│   └── schema.sql             # Relational table definitions
├── memory/
│   └── long_term.py           # ChromaDB semantic vector memory interface
├── tests/
│   └── test_suite.py          # Full automated unit test suite (29 test cases)
├── ui/
│   ├── command_bar.py         # Glassmorphism command bar HUD
│   ├── waveform.py            # Real-time audio input visualizer
│   ├── overlay.py             # Translucent screen overlay
│   └── card_manager.py        # Desktop notification & reminder card manager
├── voice/
│   ├── recorder.py            # PyAudio streaming recorder with WebRTC VAD
│   ├── stt.py                 # Faster-Whisper local speech-to-text engine
│   └── tts.py                 # Native SAPI5 Windows speech synthesizer
├── install.bat                # 1-click Windows installer script
├── main.py                    # Application bootstrap & system tray entry point
└── requirements.txt           # Python dependency manifest
```

---

## ⚙️ Configuration

Settings can be modified via the Settings UI or by editing `config/config.json`:

```json
{
  "hotkey": "ctrl+space",
  "text_hotkey": "alt+space",
  "preferred_browser": "chrome",
  "whisper_model": "tiny.en",
  "vad_aggressiveness": 1,
  "theme": "dark",
  "ai": {
    "backend_priority": ["ollama", "rule_based"],
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5:7b"
    }
  }
}
```

---

## 🧪 Running Tests

Saturday comes with a comprehensive test suite covering phrasing variance, distractor rejection, safety-critical confirmations, Windows Settings resolution, and exception containment:

```powershell
python -m unittest tests/test_suite.py -v
```

```
test_app_opening_phrasings ... ok
test_clean_entity_name ... ok
test_confirmation_flow_leaves_clean_state ... ok
test_delete_my_temp_file_phrasing ... ok
test_exception_returns_spoken_apology ... ok
test_file_delete_requires_confirmation ... ok
test_hypothetical_delete_routes_to_conversation ... ok
test_hypothetical_shutdown_routes_to_conversation ... ok
test_media_playback_commands ... ok
test_multi_site_searches ... ok
test_negative_open_statements ... ok
test_negative_statements_route_to_conversation ... ok
test_punctuation_and_capitalization_noise ... ok
test_reminder_nl_phrasings ... ok
test_restart_requires_confirmation ... ok
test_shutdown_requires_confirmation ... ok
test_windows_settings_and_system_tools_resolution ... ok
...
----------------------------------------------------------------------
Ran 29 tests in 0.069s

OK
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

<p align="center">
  Built with ❤️ for a faster, smarter, and safer Windows desktop experience.
</p>
