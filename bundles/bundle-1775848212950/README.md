# X Action Engine

AI-powered X/Twitter engagement engine. Fetches your feed, scores tweets with Papr Memory context and 80/20 prioritization, generates draft replies and quote tweets in your voice, and opens X with pre-filled text. Focus on the 20% of tweets that drive 80% of your engagement value.

## Installation

### Option 1: Import via Paprwork Agent
```
Agent: "Import the bundle from ~/Papr/bundles/bundle-1775848212950"
```

### Option 2: Import from GitHub
```
Agent: "Import the bundle from github.com/Papr-ai/paprwork-community-apps subPath bundles/bundle-1775848212950"
```

## Setup

### Required API Keys
- **ANTHROPIC_API_KEY** — for Claude scoring/drafting (auto-managed if you have Claude Pro/Max)
- **X_AUTH_TOKEN** — your X session cookie (see below)
- **X_CT0** — your X CSRF cookie (see below)

### Optional API Keys
- **GOOGLE_API_KEY** — fallback LLM (Google Gemini) if Anthropic fails
- **OPENAI_PLATFORM_KEY** — additional fallback LLM
- **PAPR_API_KEY** — enriches scoring with your Papr Memory context

### Getting X Auth Tokens via Bird Skill
The easiest way to get your X_AUTH_TOKEN and X_CT0 is through the **Bird skill** (preinstalled):

1. Make sure you're logged into x.com in Chrome
2. Ask your agent: *"Get my X auth token and CT0 from bird"*
3. Bird extracts cookies from Chrome automatically — no manual copy-paste needed

Your X handle is also auto-detected via `bird whoami`.

## Contents

- **App**: X Action Engine
- **Jobs**: 2 jobs
  - **X Feed Fetcher** — fetches your timeline + topic searches via bird CLI
  - **X Action Engine Scorer** — scores tweets, generates drafts via Claude

## How It Works

1. Feed Fetcher pulls ~80 tweets from your timeline + topic searches
2. Scorer ranks them by composite score (velocity, engagement, recency)
3. Claude picks the best 10 and generates reply/quote drafts in your voice
4. App shows scored tweets — click to open X with pre-filled text

## Version

1.0.0 - Created 2026-04-10
