import base64, json, re, sqlite3, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

GOOGLE_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
SELF_EMAIL = 'cbadcock@gmail.com'
QUERY = 'in:inbox newer_than:4d -category:promotions -category:social'
MAX_RESULTS = 100

SKIP_PATTERNS = {
    'receipt/confirmation/system': re.compile(r'\b(receipt|payment confirmation|payment received|transaction confirmation|statement available|balance alert|autopay|parking session|order confirmation|booking confirmation|travel confirmation|shipping|delivery update|subscription cancelled|subscription canceled|membership was successfully cancelled|payment scheduled|payment confirmation)\b', re.I),
    'security/verification': re.compile(r'\b(verification code|verify your|otp|one-time|one time passcode|mfa code|sign-in alert|signed in with a new device|security alert|device validation|password reset|authentication code)\b', re.I),
    'marketing/newsletter': re.compile(r'\b(unsubscribe|manage preferences|view in browser|newsletter|blog|product update|announcement|sale|shop now|special offer|promotion|recruiting team|activate your streaming subscriptions)\b', re.I),
    'appointment/reminder': re.compile(r'\b(appointment reminder|starts in [0-9]+ hours|telehealth appointment|invitation for telehealth|your video visit starts|calendar invitation|accepted:|declined:|tentative:|reminder:)\b', re.I),
    'account/subscription update': re.compile(r'\b(account update|subscription update|terms|conditions|privacy policy|policy update)\b', re.I),
}

ACTION_PATTERNS = [
    ('send_information', re.compile(r'\b(can you|could you|please)\s+(re)?send\b', re.I)),
    ('send_information', re.compile(r'\b(can you|could you|please)\s+(provide|send)\b', re.I)),
    ('upload_document', re.compile(r'\b(upload|attach)\b.*\b(document|documents|file|files|statement|statements|id|proof)\b', re.I)),
    ('submit_form', re.compile(r'\b(submit|complete|fill out)\b.*\bform\b', re.I)),
    ('review_document', re.compile(r'\b(please review|review and sign|review the attached|attached are the .* we were required to draft)\b', re.I)),
    ('follow_up', re.compile(r'\b(follow up|circle back|let me know what works|please advise)\b', re.I)),
    ('make_payment', re.compile(r'\b(payment due|invoice due|please pay|amount due)\b', re.I)),
]

PASSIVE_PAT = re.compile(r'\b(for your records|fyi|thank you for your patience|will provide an update|keep an eye out|received this email|not the right person|scheduled|confirmed|thank you for your recent|thank you for scheduling|we received|we weren.?t able to locate|automatic reply)\b', re.I)
PERSONAL_BLOCK_PAT = re.compile(r'\b(papr\.ai|papr|project|proposal|client|investor|meeting|demo|launch team|marketing professionals)\b', re.I)
NOREPLY_PAT = re.compile(r'(^|[^a-z])(no[\._-]?reply|donotreply)([^a-z]|$)', re.I)
STALE_PAT = re.compile(r'\b(yesterday|earlier this week|today at|starts in|happening soon)\b', re.I)


def api_get(url, token):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def hdrs(payload):
    return {h['name'].lower(): h['value'] for h in payload.get('headers', [])}


def sender_email(from_full):
    m = re.search(r'<([^>]+)>', from_full or '')
    return (m.group(1) if m else (from_full or '')).strip().lower()


def sender_label(from_full):
    m = re.match(r'\s*"?([^<"]+?)"?\s*<', from_full or '')
    if m:
        return m.group(1).strip()
    email = sender_email(from_full)
    return email or (from_full or '').strip() or 'sender'


def decode_payload(part):
    out = []
    mime = part.get('mimeType', '')
    data = part.get('body', {}).get('data')
    if data and mime in ('text/plain', 'text/html'):
        raw = base64.urlsafe_b64decode(data + '===').decode('utf-8', 'ignore')
        if mime == 'text/html':
            raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = unescape(re.sub(r'\s+', ' ', raw)).strip()
        if raw:
            out.append(raw)
    for child in part.get('parts', []) or []:
        out.extend(decode_payload(child))
    return out


def body_text(msg):
    payload = msg.get('payload', {})
    texts = decode_payload(payload)
    body = ' '.join(texts).strip()
    return body if body else (msg.get('snippet') or '')


def split_sentences(text):
    text = re.sub(r'\s+', ' ', text or '').strip()
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def find_proof_sentence(subject, body):
    sentences = split_sentences(body)
    for s in sentences:
        if len(s) > 300:
            continue
        low = s.lower()
        if 'please contact us if you have questions' in low:
            continue
        for kind, pat in ACTION_PATTERNS:
            if pat.search(s):
                return kind, s
    combined = subject + '. ' + body[:400]
    for kind, pat in ACTION_PATTERNS:
        if pat.search(combined):
            for s in split_sentences(combined):
                if pat.search(s):
                    return kind, s
    return None, None


def make_title(kind, from_full):
    org = sender_label(from_full)
    if kind == 'make_payment':
        return f'Make a payment: {org}'
    if kind == 'review_document':
        return f'Review document: {org}'
    if kind == 'submit_form':
        return f'Submit form: {org}'
    if kind == 'upload_document':
        return f'Upload document: {org}'
    if kind == 'send_information':
        return f'Send information: {org}'
    if kind == 'follow_up':
        return f'Follow up with: {org}'
    return None


def due_date(text, date_hdr):
    tx = text or ''
    m = re.search(r'\bby\s+([A-Z][a-z]{2,9}\s+\d{1,2}(?:,\s*\d{4})?)', tx)
    if m:
        for fmt in ('%B %d, %Y', '%b %d, %Y', '%B %d', '%b %d'):
            try:
                d = datetime.strptime(m.group(1), fmt)
                if '%Y' not in fmt:
                    base = parsedate_to_datetime(date_hdr)
                    d = d.replace(year=base.year)
                return d.date().isoformat()
            except Exception:
                pass
    return None


g = sqlite3.connect(GOOGLE_DB)
a = sqlite3.connect(ADMIN_DB)
a.row_factory = sqlite3.Row
token = g.execute("select access_token from oauth_tokens where connection_id='google:personal'").fetchone()[0]
base = 'https://gmail.googleapis.com/gmail/v1/users/me/'
list_url = f"{base}messages?q={urllib.parse.quote(QUERY)}&maxResults={MAX_RESULTS}"
message_ids = [m['id'] for m in api_get(list_url, token).get('messages', [])]

scanned = 0
inserted = 0
reasons = Counter()
now = datetime.now(timezone.utc)

for msg_id in message_ids:
    scanned += 1
    msg = api_get(f'{base}messages/{msg_id}?format=full', token)
    headers = hdrs(msg.get('payload', {}))
    subject = headers.get('subject', '')
    from_full = headers.get('from', '')
    email_addr = sender_email(from_full)
    date_hdr = headers.get('date', '')
    thread_id = msg.get('threadId', '')
    body = body_text(msg)
    combined = ' '.join([subject, msg.get('snippet', ''), body])[:12000]
    low = combined.lower()

    if a.execute("SELECT 1 FROM tasks WHERE gmail_message_id=? LIMIT 1", (msg_id,)).fetchone():
        reasons['duplicate gmail_message_id'] += 1
        continue

    if any(p.search(combined) for p in SKIP_PATTERNS.values()):
        key = next(name for name,p in SKIP_PATTERNS.items() if p.search(combined))
        reasons[key] += 1
        continue

    if NOREPLY_PAT.search(email_addr):
        reasons['noreply/system sender'] += 1
        continue

    if PERSONAL_BLOCK_PAT.search(low):
        reasons['work/internal/non-personal-admin'] += 1
        continue

    kind, proof = find_proof_sentence(subject, body)
    if not proof:
        reasons['no explicit unresolved ask'] += 1
        continue

    title = make_title(kind, from_full)
    if not title:
        reasons['invalid title pattern'] += 1
        continue

    if title.startswith('Respond to message') or title.startswith('Confirm appointment'):
        reasons['disallowed title pattern'] += 1
        continue

    if PASSIVE_PAT.search(proof):
        reasons['proof sentence is passive/status-only'] += 1
        continue

    try:
        msg_dt = parsedate_to_datetime(date_hdr)
        if msg_dt.tzinfo is None:
            msg_dt = msg_dt.replace(tzinfo=timezone.utc)
        age_days = (now - msg_dt.astimezone(timezone.utc)).total_seconds() / 86400.0
        if age_days > 4.2:
            reasons['stale item'] += 1
            continue
    except Exception:
        pass

    thread = api_get(f'{base}threads/{thread_id}?format=full', token)
    current_ts = int(msg.get('internalDate', '0'))
    later_self = False
    later_inbound = False
    for tm in thread.get('messages', []):
        ts = int(tm.get('internalDate', '0'))
        if ts <= current_ts:
            continue
        th = hdrs(tm.get('payload', {}))
        tfrom = sender_email(th.get('from', ''))
        tbody = body_text(tm)
        tcombined = ' '.join([th.get('subject',''), tm.get('snippet',''), tbody]).lower()
        if tfrom == SELF_EMAIL:
            later_self = True
        elif not NOREPLY_PAT.search(tfrom):
            later_inbound = True
        if PASSIVE_PAT.search(tcombined) and 'can you' not in tcombined and 'please' not in tcombined:
            later_inbound = True
    if later_self:
        reasons['later self reply exists'] += 1
        continue
    if later_inbound:
        reasons['later thread activity exists'] += 1
        continue

    if a.execute("SELECT 1 FROM tasks WHERE source='gmail' AND status='open' AND json_extract(source_details,'$.thread_id')=? LIMIT 1", (thread_id,)).fetchone():
        reasons['open task for same thread exists'] += 1
        continue

    sender_variants = {from_full.lower(), email_addr.lower()}
    recent_sender_rows = a.execute(
        "SELECT title, created_at, json_extract(source_details,'$.from') AS sender FROM tasks WHERE source='gmail' AND status='open' AND datetime(created_at) >= datetime('now','-10 days')"
    ).fetchall()
    similar_open = False
    for row in recent_sender_rows:
        s = (row['sender'] or '').lower()
        if any(v in s or s in v for v in sender_variants if v):
            if row['title'] == title or row['title'].split(':',1)[0] == title.split(':',1)[0]:
                similar_open = True
                break
    if similar_open:
        reasons['open similar task from same sender'] += 1
        continue

    is_personal = not PERSONAL_BLOCK_PAT.search(low)
    not_system = not any(p.search(combined) for p in SKIP_PATTERNS.values()) and not NOREPLY_PAT.search(email_addr)
    title_ok = bool(re.match(r'^(Make a payment|Review document|Submit form|Upload document|Send information|Follow up with): ', title))
    if not (proof and is_personal and not_system and title_ok):
        reasons['verification failed'] += 1
        continue

    desc = proof[:500]
    src = json.dumps({
        'subject': subject,
        'from': from_full,
        'email_date': date_hdr,
        'thread_id': thread_id,
    })
    a.execute(
        "INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) VALUES (?,?,?,?, 'open','gmail',?,?)",
        (title, desc, due_date(body, date_hdr), 2, msg_id, src)
    )
    a.commit()
    inserted += 1

summary_parts = [f'scanned {scanned}', f'inserted {inserted}']
if reasons:
    ordered = ', '.join(f"{k}: {v}" for k,v in reasons.most_common())
    summary_parts.append(f'skipped {ordered}')
print('; '.join(summary_parts))
