# Google Connector

Connect your Google accounts to Paprwork. Manages OAuth tokens for Gmail, Calendar, and Drive, with a built-in setup guide for creating your Google Cloud credentials.

## Installation

### Option 1: Import via Papr Work Agent
```
Agent: "Import the Google Connector bundle from the community apps repo"
```

### Option 2: Import from GitHub
1. Clone or download this repo
2. Import: `"Import the bundle from github.com/Papr-ai/paprwork-community-apps" subPath="bundles/google-connector"`

## Contents

- **App**: Google Connector (e460c97b-62da-4ddf-969d-874daa9ba819)
- **Jobs**: 3 job(s)
  - Google Connector Exchange (python)
  - relationship_ops_schema (python)
  - relationship_ops_google_auth (python)

## Requirements

- Papr Work v2.0.0 or later
- Python 3.8+ for Python jobs
- `GOOGLE_CLIENT_ID` — Google OAuth client ID
- `GOOGLE_CLIENT_SECRET` — Google OAuth client secret

## Version

1.0.0 - Created 2026-04-17
