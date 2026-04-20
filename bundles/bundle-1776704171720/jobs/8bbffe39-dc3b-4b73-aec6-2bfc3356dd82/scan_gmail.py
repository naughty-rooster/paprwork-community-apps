import base64, datetime as dt, email.utils, html, json, re, sqlite3, sys, urllib.parse, urllib.request
from typing import Optional, Any, Dict

OAUTH_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
CONNECTION_ID = 'google:personal'
USER_EMAIL = 'cbadcock@gmail.com'

SKIP_SUBJECT_PATTERNS = [
    r'\b(statement|receipt|invoice paid|payment received|order (?:confirmation|shipped|delivered)|tracking|newsletter|digest|weekly update|monthly update|fyi|for your information|security alert|sign in|verification code|one-time sign in link|your lab test results|results are now available)\b',
    r'\b(sale|discount|off your order|subscribe ?& ?save|price changes|promotions?)\b',
]
SKIP_FROM_PATTERNS = [r'no-?reply', r'donotreply', r'notifications?@', r'mailer-daemon', r'updates?@']
ACTION_PATTERNS = [
    r'\bplease\b', r'\bcan you\b', r'\bcould you\b', r'\bwould you\b', r'\blet me know\b', r'\bneed you to\b',
    r'\byou need to\b', r'\baction required\b', r'\bdeadline\b', r'\boverdraft\b', r'\blow balance\b', r'\bnegative balance\b',
    r'\bplease (?:review|sign|complete|confirm|reply|respond|pay|call|schedule|submit|file|upload|choose|approve)\b',
    r'\b(?:review|sign|complete|confirm|respond|reply|pay|call|submit|file|upload|choose|approve)\b.{0,40}\b(?:by|before|today|tomorrow|asap)\b',
    r'\bconfirm your\b', r'\brsvp\b'
]
NO_ACTION_PATTERNS = [
    r'\bschedule change\b', r'\bfinal confirmation\b', r'\blost hat\b', r'\bjust (?:a )?heads up\b',
    r'\bjust letting you know\b', r'\bfor your information\b', r'\bno action (?:needed|required)\b'
]
RESOLVED_PATTERNS = [r'\bconfirmed\b', r'\bfiled\b', r'\bextension filed\b', r'\bdone\b', r'\bcompleted\b', r'\btaken care of\b', r'\bscheduled\b', r'\bsounds good\b', r'\bsee you then\b', r'\bthanks[, ]+got it\b', r'\bthank you[,]? got it\b']
FINANCE_STRONG = [r'overdraft', r'negative balance', r'account frozen', r'payment failed']
FINANCE_MED = [r'low balance', r'below minimum', r'past due', r'payment due']


def db_row_dict(cur, query, params=()):
    cur.execute(query, params)
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def gmail_api(path: str, token: str, params: Optional[dict]=None) -> Any:
    url = 'https://gmail.googleapis.com/gmail/v1/users/me/' + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def parse_rfc2822(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
        if d and not d.tzinfo:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc).isoformat()
    except Exception:
        return None


def clean_text(text: str) -> str:
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def decode_body(data: str) -> str:
    if not data:
        return ''
    try:
        return base64.urlsafe_b64decode((data + '=' * (-len(data) % 4)).encode()).decode('utf-8', errors='ignore')
    except Exception:
        return ''


def extract_body(payload: dict) -> str:
    texts = []
    def walk(part):
        mime = part.get('mimeType', '')
        data = (part.get('body') or {}).get('data')
        if data and mime in ('text/plain', 'text/html', ''):
            texts.append(decode_body(data))
        for child in part.get('parts', []) or []:
            walk(child)
    walk(payload or {})
    joined = '\n'.join(t for t in texts if t)
    joined = re.split(r'\nOn .*wrote:\n', joined)[0]
    joined = re.split(r'From: .*\nSent: .*', joined)[0]
    return clean_text(joined)


def get_headers(message: dict) -> Dict[str, str]:
    hdrs = {}
    for h in message.get('payload', {}).get('headers', []):
        hdrs[h['name'].lower()] = h['value']
    return hdrs


def extract_email(addr: str) -> str:
    _, email_addr = email.utils.parseaddr(addr or '')
    return (email_addr or addr or '').strip().lower()


def is_inbound(from_addr: str) -> bool:
    sender = extract_email(from_addr)
    return bool(sender and sender != USER_EMAIL)


def subject_norm(subject: str) -> str:
    s = re.sub(r'^(re|fw|fwd):\s*', '', (subject or '').lower())
    return re.sub(r'\s+', ' ', s).strip()


def looks_marketing(subject: str, from_addr: str, body: str) -> bool:
    hay = ' '.join([subject, from_addr, body[:400]]).lower()
    return any(re.search(p, hay) for p in SKIP_SUBJECT_PATTERNS + SKIP_FROM_PATTERNS)


def looks_actionable(subject: str, body: str) -> bool:
    hay = ' '.join([subject, body[:1200]]).lower()
    explicit = any(re.search(p, hay) for p in ACTION_PATTERNS)
    if not explicit:
        return False
    if any(re.search(p, hay) for p in NO_ACTION_PATTERNS) and not any(re.search(p, hay) for p in [r'\bplease\b', r'\bcan you\b', r'\bcould you\b', r'\bneed you to\b', r'\baction required\b']):
        return False
    return True


def resolved_text(text: str) -> bool:
    t = (text or '').lower()
    return any(re.search(p, t) for p in RESOLVED_PATTERNS)


def finance_strength(subject: str, body: str) -> int:
    t = f'{subject} {body}'.lower()
    if any(re.search(p, t) for p in FINANCE_STRONG): return 3
    if any(re.search(p, t) for p in FINANCE_MED): return 2
    if any(k in t for k in ['bank', 'balance', 'account', 'credit card', 'payment']): return 1
    return 0


def infer_priority(subject: str, body: str) -> int:
    t = f'{subject} {body}'.lower()
    if any(k in t for k in ['urgent', 'asap', 'deadline', 'overdraft', 'negative balance', 'today', 'tomorrow']): return 1
    if any(k in t for k in ['confirm', 'reply', 'review', 'schedule', 'rsvp', 'submit', 'sign', 'approve', 'pay']): return 2
    return 3


def infer_due_date(subject: str, body: str, email_date_iso: Optional[str]) -> Optional[str]:
    t = f'{subject} {body}'.lower()
    base = dt.datetime.fromisoformat(email_date_iso.replace('Z', '+00:00')) if email_date_iso else dt.datetime.now(dt.timezone.utc)
    if any(k in t for k in ['today', 'by end of day', 'eod', 'asap', 'urgent', 'overdraft', 'negative balance']): return base.date().isoformat()
    if 'tomorrow' in t: return (base.date() + dt.timedelta(days=1)).isoformat()
    if any(k in t for k in ['this week', 'schedule', 'rsvp', 'confirm']): return (base.date() + dt.timedelta(days=2)).isoformat()
    return None


def make_task_title(subject: str, from_addr: str, body: str) -> str:
    s = subject_norm(subject)
    sender_name = email.utils.parseaddr(from_addr or '')[0] or extract_email(from_addr).split('@')[0]
    if any(k in s for k in ['confirm', 'invitation', 'invite', 'rsvp']): return f'Respond: {s[:80]}'
    if any(k in s for k in ['review', 'orders filed', 'document', 'sign']): return f'Review: {s[:80]}'
    if any(k in (subject + ' ' + body).lower() for k in ['overdraft', 'low balance', 'negative balance']): return f'Handle finance alert from {sender_name}'
    return f'Reply: {s[:80]}'


def summarize(subject: str, body: str, from_addr: str) -> str:
    snippet = body[:260] + ('…' if len(body) > 260 else '')
    return f'From {from_addr}. Subject: {subject}. {snippet}'


def open_similar_exists(cur, from_addr: str, subject: str) -> bool:
    sender = extract_email(from_addr)
    subj = subject_norm(subject)
    rows = cur.execute("SELECT source_details FROM tasks WHERE source='gmail' AND status='open' AND created_at >= datetime('now','-7 days')").fetchall()
    for (source_details,) in rows:
        try: sd = json.loads(source_details or '{}')
        except Exception: sd = {}
        existing_sender = extract_email(sd.get('from', ''))
        existing_subj = subject_norm(sd.get('subject', ''))
        if existing_sender == sender and (existing_subj == subj or existing_subj[:40] == subj[:40]):
            return True
    return False


oauth = sqlite3.connect(OAUTH_DB)
ocur = oauth.cursor()
admin = sqlite3.connect(ADMIN_DB)
acur = admin.cursor()
token_row = db_row_dict(ocur, "SELECT access_token FROM oauth_tokens WHERE connection_id=?", (CONNECTION_ID,))
if not token_row or not token_row['access_token']:
    print('No token for google:personal')
    sys.exit(1)
token = token_row['access_token']

q = 'in:inbox newer_than:4d -category:promotions -category:social'
msgs = gmail_api('messages', token, {'q': q, 'maxResults': 100}).get('messages', [])
scanned, inserted, skipped, candidates = len(msgs), 0, {}, []

for item in msgs:
    try:
        thread = gmail_api(f"threads/{item['threadId']}", token, {'format': 'full'})
    except Exception:
        skipped['api_error'] = skipped.get('api_error', 0) + 1
        continue
    messages = thread.get('messages', [])
    current = next((m for m in messages if m.get('id') == item['id']), None)
    if not current:
        skipped['missing_message'] = skipped.get('missing_message', 0) + 1
        continue
    headers = get_headers(current)
    subject, from_addr = headers.get('subject', ''), headers.get('from', '')
    date_iso = parse_rfc2822(headers.get('date')) or dt.datetime.fromtimestamp(int(current.get('internalDate','0'))/1000, tz=dt.timezone.utc).isoformat()
    body = extract_body(current.get('payload', {}))
    if not is_inbound(from_addr):
        skipped['not_inbound'] = skipped.get('not_inbound', 0) + 1
        continue
    if looks_marketing(subject, from_addr, body):
        skipped['newsletter/notification'] = skipped.get('newsletter/notification', 0) + 1
        continue
    if acur.execute("SELECT 1 FROM tasks WHERE gmail_message_id=? LIMIT 1", (current['id'],)).fetchone():
        skipped['duplicate_message_id'] = skipped.get('duplicate_message_id', 0) + 1
        continue
    cur_dt = dt.datetime.fromisoformat(date_iso.replace('Z', '+00:00'))
    resolved = False
    for m in messages:
        if m.get('id') == current['id']: continue
        mh = get_headers(m)
        m_dt_iso = parse_rfc2822(mh.get('date')) or dt.datetime.fromtimestamp(int(m.get('internalDate','0'))/1000, tz=dt.timezone.utc).isoformat()
        m_dt = dt.datetime.fromisoformat(m_dt_iso.replace('Z', '+00:00'))
        if m_dt <= cur_dt: continue
        m_from, m_body = mh.get('from', ''), extract_body(m.get('payload', {}))
        if not is_inbound(m_from):
            if looks_actionable(subject, body):
                resolved = True
                skipped['resolved_by_user_reply'] = skipped.get('resolved_by_user_reply', 0) + 1
                break
        elif resolved_text(' '.join([mh.get('subject',''), m_body])):
            resolved = True
            skipped['resolved_later_in_thread'] = skipped.get('resolved_later_in_thread', 0) + 1
            break
    if resolved: continue
    if not looks_actionable(subject, body):
        skipped['not_actionable'] = skipped.get('not_actionable', 0) + 1
        continue
    if open_similar_exists(acur, from_addr, subject):
        skipped['similar_open_task_exists'] = skipped.get('similar_open_task_exists', 0) + 1
        continue
    acct_match = re.search(r'(?:acct|account|ending|x)(?:\s*#?\s*|\s+in\s+)(\d{3,4})', f'{subject} {body}', re.I)
    candidates.append({
        'message_id': current['id'], 'thread_id': thread.get('id'), 'subject': subject, 'from': from_addr,
        'email_date': date_iso, 'body': body, 'finance_strength': finance_strength(subject, body),
        'finance_group': f"{extract_email(from_addr)}|{date_iso[:10]}|{acct_match.group(1) if acct_match else ''}",
    })

strongest_finance = {}
for c in candidates:
    if c['finance_strength']:
        prev = strongest_finance.get(c['finance_group'])
        if not prev or c['finance_strength'] > prev['finance_strength'] or c['email_date'] > prev['email_date']:
            strongest_finance[c['finance_group']] = c

for c in sorted(candidates, key=lambda x: x['email_date']):
    if c['finance_strength']:
        keep = strongest_finance.get(c['finance_group'])
        if keep and keep['message_id'] != c['message_id']:
            skipped['weaker_finance_alert'] = skipped.get('weaker_finance_alert', 0) + 1
            continue
    title = make_task_title(c['subject'], c['from'], c['body'])
    description = summarize(c['subject'], c['body'], c['from'])
    due_date = infer_due_date(c['subject'], c['body'], c['email_date'])
    priority = infer_priority(c['subject'], c['body'])
    source_details = json.dumps({'subject': c['subject'], 'from': c['from'], 'email_date': c['email_date'], 'thread_id': c['thread_id']})
    acur.execute("INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details, created_at, updated_at) VALUES (?,?,?,?, 'open','gmail',?,?, datetime('now'), datetime('now'))", (title, description, due_date, priority, c['message_id'], source_details))
    inserted += 1

admin.commit()
print(f'scanned={scanned}')
print(f'inserted={inserted}')
print('skipped=' + (', '.join(f'{k}={v}' for k,v in sorted(skipped.items())) or 'none'))
