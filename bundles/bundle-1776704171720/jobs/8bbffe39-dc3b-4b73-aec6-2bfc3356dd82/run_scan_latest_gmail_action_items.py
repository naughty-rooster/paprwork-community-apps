import base64, html, json, re, sqlite3, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

GOOGLE_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
REPORT = '/Users/coreybadcock/Papr/jobs/8bbffe39-dc3b-4b73-aec6-2bfc3356dd82/data/gmail_action_scan_report.json'
QUERY = 'in:inbox category:personal newer_than:4d -category:promotions -category:social'
CONNECTION_ID = 'google:personal'

RESOLUTION_PHRASES = [
    'confirmed','filed','extension filed','done','completed','taken care of','scheduled',
    'sounds good','see you then','paid','submitted','thanks got it','thank you got it',
    'payment confirmation','payment is scheduled','all set','issue resolved'
]
STATUS_ONLY_PHRASES = [
    'will provide an update','keep an eye out','we weren\'t able to locate it',
    'we were not able to locate it','sounds good','see you then','keep you posted',
    'just an update','for your information','i received this email','not the right person'
]
SKIP_SUBJECT_RE = re.compile(
    r'(^\s*(automatic reply|auto.?reply|out of office)\b|verification code|one-time sign in link|receipt|newsletter|'
    r'payment confirmation|payment scheduled|order receipt|your .* is confirmed|starts in approximately|schedule change|'
    r'final confirmation|teacher appreciation week|weekly financial alerts|security alert|available to view|statement is available)',
    re.I,
)
ACTION_RE = re.compile(
    r'\b(please\s+(reply|respond|review|confirm|complete|fill|submit|upload|send|provide|sign|advise)|'
    r'action required|response required|confirmation required|review the attached|review attached|take a look|'
    r'let me know|can you|could you|would you|need you to|you need to|you must|balance due|payment due|'
    r'amount due|past due|overdraft|low balance|submit .*form|upload .*document|send .*information|provide .*information)\b',
    re.I,
)
PAYMENT_RE = re.compile(r'\b(overdraft|low balance|payment due|amount due|past due|outstanding balance|view & pay|make a payment)\b', re.I)
LEGAL_RE = re.compile(r'\b(new orders filed|orders filed|legal filing|court|case\s+\d|petition|hearing|attached order)\b', re.I)
DOC_RE = re.compile(r'\b(please review.*document|review the attached|attached document|attached pdf|lab results.*available|review it before we chat)\b', re.I)
FORM_RE = re.compile(r'\b(form|paperwork|questionnaire|intake)\b', re.I)
UPLOAD_RE = re.compile(r'\b(upload|attach(?:ment)?)\b', re.I)
APPT_RE = re.compile(r'\b(appointment|telehealth|visit|check-in|reschedule)\b', re.I)
SECURE_MSG_RE = re.compile(r'\b(secure message|new message|portal message|clio)\b', re.I)


def api_get(token, url):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def fetch_threads(token):
    threads = []
    page = None
    while True:
        params = [('q', QUERY), ('maxResults', '100')]
        if page:
            params.append(('pageToken', page))
        url = 'https://gmail.googleapis.com/gmail/v1/users/me/threads?' + urllib.parse.urlencode(params)
        data = api_get(token, url)
        threads.extend([t['id'] for t in data.get('threads', [])])
        page = data.get('nextPageToken')
        if not page:
            return threads


def parse_dt(date_hdr, fallback_ms):
    if date_hdr:
        try:
            dt = parsedate_to_datetime(date_hdr)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(int(fallback_ms)/1000, tz=timezone.utc)


def decode_part(payload):
    out = []
    body = (payload or {}).get('body') or {}
    data = body.get('data')
    if data:
        try:
            out.append(base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', 'ignore'))
        except Exception:
            pass
    for part in (payload or {}).get('parts') or []:
        out.append(decode_part(part))
    return '\n'.join(x for x in out if x)


def clean_text(text):
    text = html.unescape(text or '')
    text = re.sub(r'<style.*?</style>|<script.*?</script>', ' ', text, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def header_map(message):
    return {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}


def sender_label(from_header):
    name, addr = parseaddr(from_header or '')
    label = (name or '').strip().strip('"')
    if label:
        label = re.sub(r'\b(no[- ]?reply|noreply|donotreply|automated email|notifications?)\b', '', label, flags=re.I).strip(' -')
    if label:
        return label
    if '@' in addr:
        return addr.split('@', 1)[1].split('.')[0].replace('-', ' ').replace('_', ' ').title()
    return (from_header or 'Unknown sender').strip()


def any_phrase(text, phrases):
    low = text.lower()
    return any(p in low for p in phrases)


def extract_due(text):
    patterns = [
        r'\b(?:due|by|before)\s+(?:on\s+)?([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
        r'\b(?:due|by|before)\s+(?:on\s+)?([A-Z][a-z]+\s+\d{1,2})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        raw = m.group(1).replace(',', '')
        for fmt in ('%B %d %Y', '%B %d'):
            try:
                dt = datetime.strptime(raw, fmt)
                if fmt == '%B %d':
                    dt = dt.replace(year=datetime.now().year)
                return dt.strftime('%Y-%m-%d')
            except Exception:
                pass
    return None


def normalize_title(subject, body, sender):
    org = sender_label(sender)
    text = (subject + ' ' + body[:1500]).lower()
    if PAYMENT_RE.search(text):
        return f'Make a payment: {org}', 1 if re.search(r'overdraft|past due', text, re.I) else 2, 'payment'
    if LEGAL_RE.search(text):
        return f'Review legal filing: {org}', 2, 'legal'
    if UPLOAD_RE.search(text) and ACTION_RE.search(text):
        return f'Upload document: {org}', 2, 'upload'
    if FORM_RE.search(text) and ACTION_RE.search(text):
        return f'Submit form: {org}', 2, 'form'
    if APPT_RE.search(text) and re.search(r'confirm|required|complete.*check-?in|complete.*paperwork', text, re.I):
        return f'Confirm appointment: {org}', 2, 'appointment'
    if SECURE_MSG_RE.search(text) and re.search(r'please reply|please respond|reply|respond|let me know|can you|could you', text, re.I):
        return f'Respond to message: {org}', 2, 'message'
    if DOC_RE.search(text) or (LEGAL_RE.search(text) and re.search(r'please review|take a look|attached', text, re.I)):
        return f'Review document: {org}', 2, 'document'
    if re.search(r'(send|provide|share) (information|documents?)', text, re.I) and ACTION_RE.search(text):
        return f'Send information: {org}', 2, 'send_info'
    if re.search(r'please reply|please respond|let me know|can you|could you|would you', text, re.I):
        return f'Respond to message: {org}', 2, 'message'
    if ACTION_RE.search(text):
        return f'Follow up with: {org}', 2, 'followup'
    return None, None, None


def notification_only(subject, body):
    text = (subject + ' ' + body[:2000]).lower()
    if SKIP_SUBJECT_RE.search(subject or ''):
        return True, 'notification_only'
    if any_phrase(text, STATUS_ONLY_PHRASES):
        return True, 'status_or_reassurance'
    if re.search(r'\b(invitation|calendar invite|video visit is confirmed|telehealth verification code)\b', text, re.I):
        return True, 'calendar_or_invite'
    if re.search(r'\b(game times|newsletter|updates|promotion|sale|discount|preparing to ship|arriving|delivered)\b', text, re.I):
        return True, 'newsletter_or_update'
    return False, None


def build_description(sender, subject, date_iso, body):
    snippet = re.sub(r'\s+', ' ', body).strip()[:280]
    if len(body) > 280:
        snippet += '…'
    return f'From {sender} on {date_iso[:10]}. Subject: {subject}. {snippet}'


def calendar_match(admin_con, subject, body):
    text = (subject + ' ' + body).lower()
    if not APPT_RE.search(text):
        return False
    rows = admin_con.execute("select title, source_details from calendar_items where event_date >= date('now','-1 day')").fetchall()
    words = {w for w in re.findall(r'[a-z]{4,}', text) if w not in {'your','this','with','from','have','that','telehealth','appointment'}}
    for row in rows:
        hay = ((row[0] or '') + ' ' + (row[1] or '')).lower()
        if sum(1 for w in words if w in hay) >= 2:
            return True
    return False


def main():
    oauth = sqlite3.connect(GOOGLE_DB)
    oauth.row_factory = sqlite3.Row
    admin = sqlite3.connect(ADMIN_DB)
    admin.row_factory = sqlite3.Row
    row = oauth.execute(
        "select t.access_token, c.email from oauth_tokens t join connections c on c.id=t.connection_id where t.connection_id=?",
        (CONNECTION_ID,),
    ).fetchone()
    token = row['access_token']
    user_email = (row['email'] or '').lower()

    thread_ids = fetch_threads(token)
    skip_counts = Counter()
    candidates = []

    for tid in thread_ids:
        if admin.execute("select 1 from tasks where source='gmail' and status='open' and json_extract(source_details,'$.thread_id')=? limit 1", (tid,)).fetchone():
            skip_counts['duplicate_open_thread'] += 1
            continue
        thread = api_get(token, f'https://gmail.googleapis.com/gmail/v1/users/me/threads/{tid}?format=full')
        msgs = []
        for m in thread.get('messages', []):
            hdr = header_map(m)
            sender = hdr.get('from', '')
            _, addr = parseaddr(sender)
            direction = 'outbound' if addr.lower() == user_email else 'inbound'
            dt = parse_dt(hdr.get('date', ''), m.get('internalDate', '0'))
            body = clean_text(decode_part(m.get('payload', {})) + ' ' + (m.get('snippet') or ''))
            msgs.append({
                'id': m['id'], 'subject': hdr.get('subject', '').strip(), 'from': sender,
                'dt': dt, 'body': body, 'direction': direction,
            })
        msgs.sort(key=lambda x: x['dt'])
        reason = 'no_explicit_action'
        chosen = None
        for i, msg in enumerate(msgs):
            if msg['direction'] != 'inbound':
                continue
            later = msgs[i+1:]
            later_inbound_text = ' '.join((x['subject'] + ' ' + x['body']) for x in later if x['direction'] == 'inbound').lower()
            if any(x['direction'] == 'outbound' for x in later):
                reason = 'resolved_by_user_reply'
                continue
            if any_phrase(later_inbound_text, RESOLUTION_PHRASES):
                reason = 'resolved_by_later_confirmation'
                continue
            skip, skip_reason = notification_only(msg['subject'], msg['body'])
            if skip:
                reason = skip_reason
                continue
            title, priority, kind = normalize_title(msg['subject'], msg['body'], msg['from'])
            if not title:
                reason = 'no_explicit_action'
                continue
            if kind == 'appointment' and calendar_match(admin, msg['subject'], msg['body']):
                reason = 'calendar_event_already_exists'
                continue
            if admin.execute("select 1 from tasks where source='gmail' and gmail_message_id=? limit 1", (msg['id'],)).fetchone():
                reason = 'duplicate_message_id'
                continue
            if admin.execute(
                "select 1 from tasks where source='gmail' and status='open' and datetime(created_at) >= datetime('now','-14 days') and json_extract(source_details,'$.from')=? and lower(title)=lower(?) limit 1",
                (msg['from'], title),
            ).fetchone():
                reason = 'duplicate_similar_open_task'
                continue
            chosen = {
                'gmail_message_id': msg['id'],
                'thread_id': tid,
                'title': title,
                'description': build_description(msg['from'], msg['subject'], msg['dt'].isoformat(), msg['body']),
                'due_date': extract_due(msg['subject'] + ' ' + msg['body']),
                'priority': priority,
                'subject': msg['subject'],
                'from': msg['from'],
                'email_date': msg['dt'].isoformat(),
                'kind': kind,
            }
            break
        if chosen:
            candidates.append(chosen)
        else:
            skip_counts[reason] += 1

    strongest = []
    finance_groups = defaultdict(list)
    for c in candidates:
        if c['kind'] == 'payment':
            finance_groups[(sender_label(c['from']).lower(), c['email_date'][:10])].append(c)
        else:
            strongest.append(c)
    for _, items in finance_groups.items():
        items.sort(key=lambda x: (0 if 'low balance' in x['description'].lower() else 1 if 'payment due' in x['description'].lower() else 2 if 'overdraft' in x['description'].lower() else 0, x['email_date']), reverse=True)
        strongest.append(items[0])
        for _ in items[1:]:
            skip_counts['weaker_finance_alert'] += 1

    inserted = []
    strongest.sort(key=lambda x: x['email_date'])
    for c in strongest:
        source_details = json.dumps({
            'subject': c['subject'],
            'from': c['from'],
            'email_date': c['email_date'],
            'thread_id': c['thread_id'],
        })
        admin.execute(
            "insert into tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) values (?, ?, ?, ?, 'open', 'gmail', ?, ?)",
            (c['title'], c['description'], c['due_date'], c['priority'], c['gmail_message_id'], source_details),
        )
        inserted.append({'title': c['title'], 'gmail_message_id': c['gmail_message_id']})
    admin.commit()

    report = {
        'scanned_count': len(thread_ids),
        'inserted_count': len(inserted),
        'skipped': dict(sorted(skip_counts.items())),
        'inserted_rows': inserted,
    }
    with open(REPORT, 'w') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
