# Meetings Manager

AI-powered meeting manager — schedule, prep, record, transcribe, summarize, and sync to memory. Features macOS-style dynamic backgrounds generated daily based on your meetings.

## Installation

### Option 1: Import via Paprwork Agent
```
Agent: "Import the bundle from /Users/amirkabbara/PAPR/bundles/meetings-manager"
```

### Option 2: Import from GitHub
1. Share the URL with others
2. They import: "Import the bundle from github.com/Papr-ai/paprwork-community-apps subPath bundles/meetings-manager"

## Contents

- **App**: Meetings Manager
- **Jobs**: 10 jobs
  - Location Background Generator (python) — generates macOS-style landscape backgrounds daily using Nano Banana 2.5
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

- `OPENAI_API_KEY` — for transcription and summarization
- `GOOGLE_API_KEY` — for background image generation (Nano Banana 2.5)
- macOS with Screen Recording permission

## What's New in v4.0.0

- macOS-style landscape backgrounds generated daily based on your meetings
- Meeting status badges (Recording, Transcribing, Summarizing, Ready)
- Improved card contrast with frosted glass backgrounds
- Past meetings styled with subtle transparency
- Sticky frosted header for tab navigation
- Auto-refresh every 30s (preserves scroll position)
- Robust stop recording flow with retries and fallback
