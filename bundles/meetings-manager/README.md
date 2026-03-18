# Meetings Manager

A complete meeting workflow app for Paprwork — schedule meetings, take live notes, record and transcribe audio, and get AI-generated summaries with smart topic tags.

## What It Does

**Before the meeting:**
- Create upcoming meetings with title, date/time, and participants
- Meetings appear in a clean dashboard sorted by date

**During the meeting:**
- Take freeform notes directly in the app
- Record audio with one click — transcription happens automatically via Whisper

**After the meeting:**
- The Meeting Summarizer job processes pending transcripts
- Generates structured summaries: Overview, Key Decisions, Action Items, Follow-ups
- Auto-tags meetings with 2-5 topic labels (e.g. "Product", "Engineering", "Q2 Planning")
- Your handwritten notes are woven into the summary as high-priority context

## What's Included

| Component | Description |
|-----------|-------------|
| **Meetings Manager App** | Interactive UI — create, browse, record, and review meetings |
| **Meeting Summarizer Job** | AI agent that processes transcripts and generates summaries + tags |

## Requirements

- **Paprwork v2.0.0+**
- **ANTHROPIC_API_KEY** — Powers the AI summarizer (Claude)

## Installation

Import this bundle through Paprwork:
- From GitHub: `Import the bundle from github.com/Papr-ai/paprwork-community-apps`
- Or via the **Community Apps** tab in Paprwork

## How It Works

1. Open the Meetings Manager app and create a meeting
2. During the meeting, take notes and/or hit Record to capture audio
3. Audio is transcribed locally via Whisper
4. Run the Meeting Summarizer job (or set it on a schedule)
5. The AI agent reads pending transcripts + your notes, generates a summary, and writes it back
6. View the complete summary and tags in the app

## Version

1.0.0 — March 2026
