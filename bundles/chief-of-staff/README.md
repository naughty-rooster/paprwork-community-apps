# Chief of Staff

Your personal chief of staff — triages email, texts, and calendar into a daily brief, surfaces what matters, and keeps your week on track.

## What it does

- **Scans Gmail** for real action items (not noise, confirmations, or marketing)
- **Reads iMessages** to create tasks from texts you send to yourself
- **Writes to Google Calendar** when appointment texts contain real scheduling info
- **Daily morning brief** — surfaces top priorities, overdue items, and what to do first
- **Focus tab** — ranked Top 3, project-aware context, directive "What to do next"
- **Add & Review** — inbox for new auto-created tasks to triage
- **Projects** — organize tasks into active projects with planning support

## Requirements

- **ANTHROPIC_API_KEY** — for agent jobs (Gmail scanner, reconciler, daily digest, project planner)
- **GOOGLE_CLIENT_SECRET** — for Gmail and Google Calendar access

## Installation

1. Import this bundle in Paprwork
2. Add your API keys in Settings → Custom API Keys
3. Run `admin_db_setup` once to initialize the database
4. Run `admin_calendar_sync` to pull your Google Calendar events
5. The Gmail scanner and messages scanner will run automatically on their schedules

## Jobs included

| Job | Schedule | Purpose |
|-----|----------|---------|
| admin_db_setup | manual | Initialize database schema |
| admin_gmail_scanner | 7am daily | Scan Gmail for action items |
| admin_gmail_reconciler | every 20 min | Close resolved/false-positive tasks |
| admin_daily_digest | 8am daily | Generate priority digest |
| admin_messages_scanner | every 10 min | Scan iMessages for tasks |
| admin_messages_calendar_writer | every 15 min | Write appointment texts to calendar |
| admin_calendar_sync | 6:30am daily | Sync Google Calendar events |
| admin_email_to_task | every 15 min | Email-to-task pipeline |
| admin_recurring_tasks | 6:05am daily | Generate recurring tasks |
| admin_project_planner | on demand | AI project planning |

## Notes

- Uses Apple Messages (iMessage) on macOS — no Twilio required
- Tasks created from messages default to 3 business days out if no due date is specified
- The Focus tab generates a morning brief from your current task and calendar state
