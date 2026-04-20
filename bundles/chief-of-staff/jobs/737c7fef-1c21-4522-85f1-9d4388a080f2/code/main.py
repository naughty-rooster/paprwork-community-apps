"""
Email-to-Task Ingester
Scans Gmail for quick self-sent task notes and converts them into tasks.
"""
import base64, json, os, re, sqlite3
from datetime import datetime, timedelta, timezone

import requests

GOOGLE_DB = "/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db"
ADMIN_DB = "/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db"
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_LIST = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_GET = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{}"

PREFIX_RE = re.compile(r'^\s*(task|todo|reminder|add task)\b\s*[:\-]?\s*', re.IGNORECASE)
DAY_MAP = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def get_access_token():
    conn = sqlite3.connect(GOOGLE_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT c.email, c.metadata_json, t.access_token, t.refresh_token, t.expires_at "
        "FROM connections c JOIN oauth_tokens t ON t.connection_id=c.id WHERE c.id='google:personal'"
    ).fetchone()
    if not row:
        raise RuntimeError("No Google connection found. Connect Google in the Google Connector app first.")
    meta = json.loads(row["metadata_json"] or "{}")
    client_id = meta.get("client_id", "").strip()
    access_token = (row["access_token"] or "").strip()
    refresh_token = (row["refresh_token"] or "").strip()
    expires_at = (row["expires_at"] or "").strip()
    email = row["email"]

    needs_refresh = True
    if access_token and expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp > datetime.now(timezone.utc) + timedelta(minutes=5):
                needs_refresh = False
        except Exception:
            pass

    if needs_refresh and refresh_token:
        r = requests.post(TOKEN_URL, data={
            "client_id": client_id, "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token, "grant_type": "refresh_token"
        }, timeout=30)
        if r.status_code < 400:
            t = r.json()
            access_token = t["access_token"]
            exp = datetime.now(timezone.utc) + timedelta(seconds=t.get("expires_in", 3600))
            conn.execute(
                "UPDATE oauth_tokens SET access_token=?, expires_at=?, updated_at=CURRENT_TIMESTAMP WHERE connection_id='google:personal'",
                (access_token, exp.isoformat())
            )
            conn.commit()
    conn.close()
    return access_token, email


def gmail_get(url, token, params=None):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def decode_body(part):
    data = ((part.get("body") or {}).get("data") or "").strip()
    if not data:
        return ""
    padded = data + ("=" * (-len(data) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_text(payload):
    mime = (payload.get("mimeType") or "").lower()
    if mime == "text/plain":
        return decode_body(payload).strip()
    if mime == "text/html":
        text = re.sub(r"<[^>]+>", " ", decode_body(payload))
        return re.sub(r"\s+", " ", text).strip()
    texts = []
    for part in payload.get("parts") or []:
        t = extract_text(part)
        if t:
            texts.append(t)
    return "\n".join(texts).strip()


def get_header(payload, name):
    for h in (payload.get("headers") or []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def next_weekday(today, day_num, force_next_week=False):
    days_ahead = (day_num - today.weekday()) % 7
    if force_next_week or days_ahead == 0:
        days_ahead = days_ahead or 7
    return today + timedelta(days=days_ahead)


def end_of_week(today=None):
    today = today or datetime.now().date()
    return today + timedelta(days=(6 - today.weekday()))


def three_business_days(today=None):
    """Return a date 3 business days from today, skipping weekends."""
    d = today or datetime.now().date()
    count = 0
    while count < 3:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def parse_due_date_from_text(text):
    today = datetime.now().date()
    text_lower = (text or "").lower()

    if any(p in text_lower for p in ["today", "tonight", "this evening"]):
        return today.isoformat()
    if any(p in text_lower for p in ["tomorrow", "tmrw", "tmr"]):
        return (today + timedelta(days=1)).isoformat()

    for prefix, offset in [("this weekend", 5), ("next weekend", 12)]:
        if prefix in text_lower:
            return (today + timedelta(days=(offset - today.weekday()) % 7 or 7)).isoformat()

    for match in re.finditer(r'\b(?:(this|next)\s+)?(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thurs|friday|fri|saturday|sat|sunday|sun)\b', text_lower):
        modifier, day_text = match.groups()
        day_num = DAY_MAP[day_text]
        force_next = modifier == "next"
        date_val = next_weekday(today, day_num, force_next_week=force_next)
        return date_val.isoformat()

    slash_match = re.search(r'\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b', text_lower)
    if slash_match:
        month, day = int(slash_match.group(1)), int(slash_match.group(2))
        year = int(slash_match.group(3)) if slash_match.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            date_val = datetime(year, month, day).date()
            if not slash_match.group(3) and date_val < today:
                date_val = datetime(today.year + 1, month, day).date()
            return date_val.isoformat()
        except ValueError:
            pass

    month_match = re.search(
        r'\b(' + '|'.join(MONTH_MAP.keys()) + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(\d{4}))?\b',
        text_lower
    )
    if month_match:
        month = MONTH_MAP[month_match.group(1)]
        day = int(month_match.group(2))
        year = int(month_match.group(3)) if month_match.group(3) else today.year
        try:
            date_val = datetime(year, month, day).date()
            if not month_match.group(3) and date_val < today:
                date_val = datetime(today.year + 1, month, day).date()
            return date_val.isoformat()
        except ValueError:
            pass

    return None


def parse_priority_from_text(subject, body, due_date=None):
    combined = f"{subject} {body}".lower()
    if any(w in combined for w in ["urgent", "asap", "immediately", "emergency", "critical"]) or combined.count("!") >= 2:
        return 1
    if due_date == datetime.now().date().isoformat() or any(w in combined for w in ["today", "tonight", "this afternoon", "this morning"]):
        return 1
    if any(w in combined for w in ["important", "high priority", "soon", "tomorrow", "this week"]):
        return 2
    if any(w in combined for w in ["low priority", "whenever", "sometime", "no rush", "eventually"]):
        return 4
    return 2


def extract_task_title(subject, body):
    raw = PREFIX_RE.sub('', subject or '').strip()
    if raw:
        return normalize_whitespace(raw)
    first_line = (body or '').splitlines()[0] if body else ''
    return normalize_whitespace(first_line)[:120] or "Task from email"


def build_description(body, title):
    cleaned = normalize_whitespace(body)
    if not cleaned:
        return ""
    if cleaned.lower() == title.lower():
        return ""
    return cleaned[:500]


def is_valid_task_subject(subject):
    return bool(PREFIX_RE.match(subject or ''))


def main():
    token, account_email = get_access_token()
    query = 'in:anywhere newer_than:30d (subject:"task" OR subject:"todo" OR subject:"reminder" OR subject:"add task")'
    result = gmail_get(GMAIL_LIST, token, {"maxResults": 50, "q": query})
    messages = result.get("messages") or []
    print(f"Found {len(messages)} candidate emails")

    admin_conn = sqlite3.connect(ADMIN_DB)
    admin_conn.row_factory = sqlite3.Row
    admin_conn.execute("PRAGMA journal_mode=WAL")
    admin_conn.execute("PRAGMA busy_timeout=30000")

    inserted = 0
    skipped = {"existing": 0, "not_self": 0, "subject": 0}
    for msg in messages:
        msg_id = msg["id"]
        existing = admin_conn.execute("SELECT id FROM tasks WHERE gmail_message_id=?", (msg_id,)).fetchone()
        if existing:
            skipped["existing"] += 1
            continue

        full = gmail_get(GMAIL_GET.format(msg_id), token)
        payload = full.get("payload") or {}
        subject = get_header(payload, "subject")
        from_addr = get_header(payload, "from")
        to_addr = get_header(payload, "to")
        body = extract_text(payload)[:2000]
        internal_date = full.get("internalDate")
        email_date = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).date().isoformat() if internal_date else None

        acct = (account_email or '').lower()
        from_l = (from_addr or '').lower()
        to_l = (to_addr or '').lower()
        if acct and (acct not in from_l or acct not in to_l):
            skipped["not_self"] += 1
            continue
        if not is_valid_task_subject(subject):
            skipped["subject"] += 1
            continue

        title = extract_task_title(subject, body)
        due_date = parse_due_date_from_text(f"{subject}\n{body}") or three_business_days().isoformat()
        priority = parse_priority_from_text(subject, body, due_date)
        description = build_description(body, title)
        source_details = json.dumps({
            "subject": subject,
            "from": from_addr,
            "to": to_addr,
            "body_preview": body[:200],
            "email_date": email_date,
            "capture_mode": "self_email",
        })

        admin_conn.execute(
            """INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details)
               VALUES (?,?,?,?,'open','email_in',?,?)""",
            (title, description, due_date, priority, msg_id, source_details)
        )
        inserted += 1
        print(f"  ✓ Task: '{title}' | priority={priority} | due={due_date}")

    admin_conn.commit()
    admin_conn.close()
    print(f"\nDone. Inserted {inserted} new tasks from email. Skipped: {skipped}")


if __name__ == "__main__":
    main()
