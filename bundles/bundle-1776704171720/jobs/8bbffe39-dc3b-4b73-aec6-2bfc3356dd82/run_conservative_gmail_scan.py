import base64, json, re, sqlite3, urllib.parse, urllib.request
from collections import Counter, defaultdict
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

GOOGLE_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
JOB_DIR = '/Users/coreybadcock/Papr/jobs/8bbffe39-dc3b-4b73-aec6-2bfc3356dd82'
REPORT = f'{JOB_DIR}/scan_report.json'
SELF_EMAIL = 'cbadcock@gmail.com'
QUERY = 'in:inbox newer_than:4d -category:promotions -category:social'
MAX_RESULTS = 40

RESOLVED_PAT = re.compile(r'\b(confirmed|filed|extension filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks[, ]+got it|thanks got it|resolved|canceled|cancelled)\b', re.I)
PASSIVE_PAT = re.compile(r'(will provide an update|keep an eye out|we weren.t able to locate it|sounds good|see you then|fyi|for your records)', re.I)
MARKETING_PAT = re.compile(r'(unsubscribe|manage preferences|view in browser|sponsored|promotion|deal|sale|shop now|register now)', re.I)
RECEIPT_PAT = re.compile(r'(receipt|refund is confirmed|order receipt|payment receipt|subscription canceled|subscription cancelled|your membership was successfully cancelled|confirmation)', re.I)
ALERT_PAT = re.compile(r'(verification code|mfa code|security alert|sign in from a new device|large transaction notice|big deposit incoming)', re.I)
CAL_PAT = re.compile(r'^(invitation:|accepted:|declined:|tentative:)', re.I)


def jget(url, token):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def headers_map(payload):
    return {h['name'].lower(): h['value'] for h in payload.get('headers', [])}


def sender_email(from_full):
    m = re.search(r'<([^>]+)>', from_full or '')
    return (m.group(1) if m else (from_full or '')).strip().lower()


def sender_name(from_full):
    if not from_full:
        return ''
    m = re.match(r'\s*"?([^<"]+?)"?\s*<', from_full)
    if m:
        return m.group(1).strip()
    if '@' in from_full:
        return from_full.split('@', 1)[0].strip()
    return from_full.strip()


def decode_parts(part):
    texts = []
    mt = part.get('mimeType', '')
    data = part.get('body', {}).get('data')
    if data and mt in ('text/plain', 'text/html'):
        raw = base64.urlsafe_b64decode(data + '===').decode('utf-8', 'ignore')
        if mt == 'text/html':
            raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = unescape(re.sub(r'\s+', ' ', raw)).strip()
        if raw:
            texts.append(raw)
    for child in part.get('parts', []) or []:
        texts.extend(decode_parts(child))
    return texts


def normalize_title(subject, from_full, body):
    org = sender_name(from_full) or sender_email(from_full) or 'sender'
    s = (subject or '').strip()
    b = (body or '').lower()
    sl = s.lower()
    if 'payment due' in sl or 'make a payment' in b or 'balance due' in b or ('payment' in sl and 'scheduled' not in sl):
        return f'Make a payment: {org}'
    if any(x in sl for x in ['legal filing', 'orders filed', 'petition', 'motion', 'court']) or any(x in b for x in ['attached are the orders', 'motion for reconsideration', 'legal filing']):
        return f'Review legal filing: {org}'
    if any(x in b for x in ['please review', 'review the attached', 'attached are the', 'please see attached', 'document attached']):
        return f'Review document: {org}'
    if any(x in b for x in ['please confirm', 'confirm your appointment', 'confirm appointment', 'reply c to confirm']):
        return f'Confirm appointment: {org}'
    if any(x in b for x in ['submit', 'complete this form', 'fill out', 'application']) and 'submit' in b:
        return f'Submit form: {org}'
    if 'upload' in b:
        return f'Upload document: {org}'
    if any(x in b for x in ['can you send', 'please send', 'resend', 'send over', 'provide', 'information requested']):
        return f'Send information: {org}'
    if any(x in b for x in ['follow up', 'circle back']):
        return f'Follow up with: {org}'
    return f'Respond to message: {org}'


def explicit_action(subject, body):
    text = f'{subject} {body}'.lower()
    asks = [
        'can you', 'could you', 'please reply', 'please respond', 'please confirm',
        'let me know', 'reply to this email', 'we need', 'need you to', 'please send',
        'can you resend', 'please resend', 'pay by', 'payment due', 'action required',
        'please review', 'review and sign', 'submit', 'upload', 'complete this form'
    ]
    return any(a in text for a in asks)


def due_date_from_subject_date(date_header):
    try:
        return parsedate_to_datetime(date_header).date().isoformat()
    except Exception:
        return None


g = sqlite3.connect(GOOGLE_DB)
a = sqlite3.connect(ADMIN_DB)
a.row_factory = sqlite3.Row
token = g.execute("select access_token from oauth_tokens where connection_id='google:personal'").fetchone()[0]
base = 'https://gmail.googleapis.com/gmail/v1/users/me/'
list_url = f"{base}messages?q={urllib.parse.quote(QUERY)}&maxResults={MAX_RESULTS}"
message_ids = [m['id'] for m in jget(list_url, token).get('messages', [])]

scanned = 0
inserted = 0
skip_counts = Counter()
inserted_rows = []
strongest_finance = {}
open_sender_titles = defaultdict(list)
for row in a.execute("SELECT lower(coalesce(json_extract(source_details,'$.from'),'')) AS sender, lower(title) AS title FROM tasks WHERE status='open' AND source='gmail' AND created_at >= datetime('now','-14 days')"):
    open_sender_titles[row['sender']].append(row['title'])

for msg_id in message_ids:
    scanned += 1
    msg = jget(f'{base}messages/{msg_id}?format=full', token)
    hdr = headers_map(msg.get('payload', {}))
    subject = hdr.get('subject', '')
    from_full = hdr.get('from', '')
    date_header = hdr.get('date', '')
    thread_id = msg.get('threadId', '')
    snippet = (msg.get('snippet') or '').replace('\n', ' ')
    parts = decode_parts(msg.get('payload', {}))
    body = ' '.join(parts)[:8000] if parts else snippet
    combined = f'{subject} {snippet} {body}'.lower()
    sender = sender_email(from_full)
    norm_title = normalize_title(subject, from_full, body)

    if a.execute('SELECT 1 FROM tasks WHERE gmail_message_id=? LIMIT 1', (msg_id,)).fetchone():
        skip_counts['duplicate gmail_message_id'] += 1
        continue
    if a.execute("SELECT 1 FROM tasks WHERE source='gmail' AND json_extract(source_details,'$.thread_id')=? AND status='open' LIMIT 1", (thread_id,)).fetchone():
        skip_counts['open task already exists for thread'] += 1
        continue
    recent_similar = any(t == norm_title.lower() for t in open_sender_titles.get(from_full.lower(), [])) or any(t == norm_title.lower() for t in open_sender_titles.get(sender, []))
    if recent_similar:
        skip_counts['similar open task from same sender'] += 1
        continue

    thread = jget(f'{base}threads/{thread_id}?format=full', token)
    msg_ts = int(msg.get('internalDate', '0'))
    later_self = False
    later_resolved = False
    for tm in thread.get('messages', []):
        th = headers_map(tm.get('payload', {}))
        ts = int(tm.get('internalDate', '0'))
        if ts <= msg_ts:
            continue
        tf = th.get('from', '').lower()
        tcombined = f"{th.get('subject','')} {tm.get('snippet','')} {' '.join(decode_parts(tm.get('payload', {})))[:4000]}".lower()
        if SELF_EMAIL in tf:
            later_self = True
        if RESOLVED_PAT.search(tcombined) or PASSIVE_PAT.search(tcombined):
            later_resolved = True
    if later_self:
        skip_counts['later self reply resolved thread'] += 1
        continue
    if later_resolved:
        skip_counts['later inbound resolved/status-only thread'] += 1
        continue

    if CAL_PAT.search(subject):
        skip_counts['calendar invitation/info only'] += 1
        continue
    if RECEIPT_PAT.search(combined):
        skip_counts['receipt/confirmation/cancellation'] += 1
        continue
    if ALERT_PAT.search(combined):
        skip_counts['generic alert/notification'] += 1
        continue
    if MARKETING_PAT.search(combined) or 'executive recruiting team at linkedin' in combined:
        skip_counts['marketing/recruiting'] += 1
        continue
    if PASSIVE_PAT.search(combined):
        skip_counts['status/reassurance only'] += 1
        continue
    if 'games this saturday' in combined or 'reminder:' in combined or 'looking forward to seeing you' in combined:
        skip_counts['schedule reminder with no reply needed'] += 1
        continue
    if 'we’re on it' in combined or "we're on it" in combined or 'we will send you an update' in combined:
        skip_counts['support acknowledgement only'] += 1
        continue
    if 'experian' in combined and 'lock your credit file' in combined:
        skip_counts['product onboarding prompt'] += 1
        continue
    if not explicit_action(subject, body):
        skip_counts['no explicit ask or obligation'] += 1
        continue

    finance_strength = None
    if 'low balance' in combined:
        finance_strength = 1
    elif 'overdraft' in combined or 'payment due' in combined:
        finance_strength = 2
    if finance_strength:
        day = due_date_from_subject_date(date_header) or 'unknown'
        key = (sender, day)
        prev = strongest_finance.get(key)
        if prev and prev[0] >= finance_strength:
            skip_counts['weaker same-day finance alert'] += 1
            continue
        strongest_finance[key] = (finance_strength, msg_id)

    description = snippet.strip() or subject.strip()
    source_details = json.dumps({
        'subject': subject,
        'from': from_full,
        'email_date': date_header,
        'thread_id': thread_id,
    })
    a.execute(
        "INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) VALUES (?,?,?,?,?,?,?,?)",
        (norm_title, description[:500], due_date_from_subject_date(date_header), 2, 'open', 'gmail', msg_id, source_details),
    )
    a.commit()
    inserted += 1
    inserted_rows.append({'id': msg_id, 'title': norm_title, 'from': from_full})

report = {
    'scanned': scanned,
    'inserted': inserted,
    'inserted_rows': inserted_rows,
    'skipped': dict(skip_counts),
}
Path(REPORT).write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
