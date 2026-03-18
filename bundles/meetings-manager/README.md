# Meetings Manager

Your entire meeting lifecycle in one app — from calendar sync to AI-powered notes, all running locally on your Mac.

## How It Works

### Before the Meeting
The app reads your macOS Calendar and shows today's meetings. One minute before a meeting starts, you get a **native macOS notification** with a Record button. It also detects active Zoom, Google Meet, and Teams calls — even unscheduled ones — and prompts you to record.

For important meetings, hit **Prep** to generate an AI research doc: attendee profiles (via Apollo), prior meeting context from PAPR Memory, open action items, and suggested talking points.

### During the Meeting
Hit Record to capture system audio. Take notes in the **Notes** tab while recording — your notes get woven into the final AI summary, not kept separate.

### After the Meeting
The pipeline runs automatically:

1. **Transcribe** — Whisper converts the recording to text (auto-compresses large files to stay under API limits)
2. **Summarize** — AI generates structured notes: overview, key decisions, action items, follow-ups. Your in-meeting notes are merged in as highlights.
3. **Sync to Memory** — Meetings, participants, decisions, and action items are stored in PAPR Memory for future recall across all your tools.

## The Pipeline

```
Calendar Reader (every 5 min)          Meeting Monitor (every 1 min)
        |                                       |
   Syncs events to DB                  Detects active calls
        |                              Sends notifications
   Meeting Prep Agent (on demand)               |
        |                              User clicks Record
   Generates prep doc                           |
                                       System Audio Recorder
                                                |
                                       Whisper Transcriber
                                                |
                                       Meeting Summarizer
                                                |
                                       Meeting Memory Sync
```

## Jobs

| Job | What It Does |
|-----|-------------|
| **Calendar Reader** | Reads macOS Calendar via EventKit (Swift/Python bridge), syncs events + attendees to SQLite |
| **Meeting Monitor** | Runs every minute. Checks calendar for imminent meetings, detects Zoom/Meet/Teams processes, sends native macOS notifications with Record button |
| **System Audio Recorder** | Captures system audio via a lightweight Swift recorder binary |
| **Stop Recorder** | Sends stop signal to the recorder process |
| **Check Screen Recording Permission** | Verifies macOS screen recording permission is granted |
| **Whisper Transcriber** | Sends audio to OpenAI Whisper API. Auto-compresses large WAV files to MP3 via ffmpeg |
| **Meeting Summarizer** | AI agent that summarizes transcripts, merges user notes, generates topic tags |
| **Meeting Memory Sync** | AI agent that stores meetings, participants, action items, and decisions to PAPR Memory |
| **Meeting Prep Agent** | AI agent that researches attendees (Apollo/Exa), pulls prior context from Memory, generates prep docs |

## Requirements

| Key | Required | Used By |
|-----|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | Summarizer, Memory Sync, Prep Agent |
| `OPENAI_PLATFORM_KEY` | Yes | Whisper transcription |
| `PAPR_MEMORY_API_KEY` | Optional | Memory Sync (structured memory storage) |
| `APOLLO_API_KEY` | Optional | Prep Agent (attendee profile enrichment) |
| `EXA_API_KEY` | Optional | Prep Agent (web search for meeting context) |

### System Dependencies

- **macOS** — uses EventKit for calendar access and system audio capture
- **ffmpeg** — for compressing large audio files (`brew install ffmpeg`)
- **terminal-notifier** — for native notifications with action buttons (`brew install terminal-notifier`)
- **Screen Recording permission** — required for system audio capture (System Settings → Privacy → Screen Recording → allow Paprwork)

## Install

Import via Paprwork's **Community Apps** tab, or manually:

```
Import App Bundle → ~/PAPR/bundles/meetings-manager
```

After import:
1. Add your API keys in **Settings → API Keys → Custom API Keys**
2. Grant Screen Recording permission when prompted
3. The Calendar Reader and Meeting Monitor jobs will start automatically
