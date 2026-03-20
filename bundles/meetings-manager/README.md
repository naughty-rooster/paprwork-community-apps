# undefined

AI-powered meeting manager with location-aware backgrounds, calendar integration, recording, transcription, and summarization. Liquid Glass design.

## Installation

### Option 1: Import via Paprwork Agent
```
Agent: "Import the meetings-manager bundle from github.com/Papr-ai/paprwork-community-apps"
```

### Option 2: Import from GitHub
1. Clone this repo
2. Import: `"Import the bundle from bundles/meetings-manager"`

## API Keys

### Required
- **OPENAI_API_KEY** — Used for Whisper audio transcription

### Optional
- **GOOGLE_API_KEY** — Enables AI-generated location-aware backgrounds via Gemini. Without it, the app uses a beautiful gradient fallback.
- **APOLLO_API_KEY** — Enriches meeting prep with contact data
- **EXA_API_KEY** — Enriches meeting prep with web search

## Contents

- **App**: Meetings Manager
- **Jobs**: 10 job(s)
  - Location Background Generator (python) — *requires GOOGLE_API_KEY*
  - Check Screen Recording Permission (bash)
  - Whisper Transcriber (python)
  - Stop Recorder (bash)
  - System Audio Recorder (bash)
  - Meeting Memory Sync (agent)
  - Meeting Summarizer (agent)
  - Calendar Reader (bash)
  - Meeting Prep Agent (agent)
  - Meeting Monitor (bash)

## Requirements

- Paprwork v2.0.0 or later
- macOS (screen recording uses native APIs)
- Python 3.8+ for Python jobs

## Version

3.0.0 - Created 2026-03-19
