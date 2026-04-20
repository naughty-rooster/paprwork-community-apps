import base64, datetime as dt, html, json, re, sqlite3, sys, urllib.parse, urllib.request
from email.utils import parseaddr
from html.parser import HTMLParser

GOOGLE_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
USER_EMAIL = 'cbadcock@gmail.com'

class Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ('style', 'script') and self.skip: self.skip -= 1
    def handle_data(self, data):
        if data and not self.skip:
            self.parts.append(data)
    def get(self):
        return ' '.join(self.parts)

def strip_html(s):
    if not s:
        return ''
    p = Stripper()
    try:
        p.feed(s)
        return html.unescape(p.get())
    except Exception:
        return s

def b64url_decode(data):
    if not data:
        return ''
    data += '=' * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data.encode()).decode('utf-8', errors='ignore')
    except Exception:
        return ''

def header_map(headers):
    return {h.get('name','').lower(): h.get('value','') for h in headers or []}

def extract_text_from_payload(payload):
    texts = []
    def walk(part):
        mime = (part.get('mimeType') or '').lower()
        body = (part.get('body') or {}).get('data')
        if mime == 'text/plain' and body:
            texts.append(b64url_decode(body))
        elif mime == 'text/html' and body:
            texts.append(strip_html(b64url_decode(body)))
        for sp in part.get('parts') or []:
            walk(sp)
    walk(payload or {})
    text = '\n'.join(t for t in texts if t).strip()
    text = re.sub(r'\r', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text[:12000]

def api_get(url, token):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def list_messages(token):
    q = 'in:inbox newer_than:4d -category:promotions -category:social'
    params = urllib.parse.urlencode({'q': q, 'maxResults': 100, 'includeSpamTrash': 'false', 'labelIds': 'INBOX'})
    out = api_get(f'https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}', token)
    msgs = out.get('messages') or []
    while out.get('nextPageToken') and len(msgs) < 200:
        params = urllib.parse.urlencode({'q': q, 'maxResults': 100, 'includeSpamTrash': 'false', 'labelIds': 'INBOX', 'pageToken': out['nextPageToken']})
        out = api_get(f'https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}', token)
        msgs.extend(out.get('messages') or [])
    return msgs

def get_thread(thread_id, token):
    return api_get(f'https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}?format=full', token)

def clean_sender(from_header):
    name, addr = parseaddr(from_header or '')
    return (name.strip('"') or addr.split('@')[0] or addr or from_header).strip(), addr.lower()

def clean_subject(subject):
    return re.sub(r'^(re|fwd?|fw):\s*', '', subject or '', flags=re.I).strip()

def lower_text(*parts):
    return ' '.join([p for p in parts if p]).lower()

NOISE_SENDER_PATTERNS = ['no-reply', 'noreply', 'donotreply', 'notifications@', 'mailer-daemon', 'auto-confirm', 'automated email']
MARKETING_HINTS = ['unsubscribe', 'view in browser', 'manage preferences', 'sale', 'discount', 'promo', 'offer expires', 'welcome digital marketing professionals', 'where talent meets opportunity']
RESOLUTION_WORDS = ['confirmed', 'filed', 'extension filed', 'done', 'completed', 'taken care of', 'scheduled', 'sounds good', 'see you then', 'paid', 'submitted', 'thanks got it', 'thank you got it']
STATUS_ONLY_PHRASES = ['will provide an update', 'keep an eye out', "weren't able to locate it", 'we were not able to locate it', 'sounds good', 'see you then', 'you are now sharing data', 'verification code', 'sign in link']
ACTION_PATTERNS = [
    ('make_payment', re.compile(r'\b(payment due|pay now|amount due|past due|balance due|invoice due|autopay failed|overdraft|low balance|insufficient funds)\b', re.I)),
    ('review_legal', re.compile(r'\b(order filed|orders filed|legal filing|pleading|court|hearing|petition|case\s+\d|notice of|declaration|motion)\b', re.I)),
    ('review_doc', re.compile(r'\b(review (the )?(document|form|statement|attachment)|document attached|please review|needs your review|signature requested|sign this document)\b', re.I)),
    ('confirm_appt', re.compile(r'\b(confirm (your )?(appointment|telehealth|visit)|please confirm|appointment confirmation required|check in for your appointment)\b', re.I)),
    ('submit_form', re.compile(r'\b(complete|submit|fill out|return) (the )?(form|paperwork|questionnaire|survey|application)\b', re.I)),
    ('upload_doc', re.compile(r'\b(upload|attach|send) (a |the )?(document|documents|file|files|photo|photos|proof|id)\b', re.I)),
    ('respond_msg', re.compile(r'\b(please reply|let me know|can you|could you|would you|reply to this|respond|need your answer|what do you think|are you able)\b', re.I)),
    ('follow_up', re.compile(r'\b(follow up|check back|circle back)\b', re.I)),
]
FINANCE_WORDS = re.compile(r'\b(overdraft|low balance|payment due|past due|balance due|autopay failed|insufficient funds)\b', re.I)
APPOINTMENT_WORDS = re.compile(r'\b(appointment|telehealth|visit|session|check-in)\b', re.I)

def classify_action(subject, body, sender_name, sender_email, snippet=''):
    text = lower_text(subject, snippet, (body or '')[:1000])
    for kind, pat in ACTION_PATTERNS:
        if pat.search(text):
            return kind
    if FINANCE_WORDS.search(text):
        return 'make_payment'
    if APPOINTMENT_WORDS.search(text) and re.search(r'\b(confirm|required|complete forms|paperwork|check in)\b', text):
        return 'confirm_appt'
    if re.search(r'\b(statement available|new statement|document available)\b', text) and 'please review' not in text:
        return None
    return None

def normalized_title(kind, sender_name, sender_email, subject, body):
    org = sender_name.strip() if sender_name else sender_email.split('@')[0]
    org = re.sub(r'\b(automated email|notifications?|support services|washington|inc\.?|llc|pllc)\b', '', org, flags=re.I)
    org = re.sub(r'\s{2,}', ' ', org).strip(' -,:') or sender_name or sender_email
    text = lower_text(subject, body)
    if 'mindful' in text or 'advancedmd.com' in sender_email:
        org = 'Mindful Therapy Group'
    elif 'seattle city light' in text:
        org = 'Seattle City Light'
    elif 'de maar' in text or 'demaarlaw' in sender_email:
        org = 'de Maar Law'
    elif 'weinrich' in text:
        org = 'Weinrich Immigration Law'
    elif 'chase' in text or 'chase.com' in sender_email:
        org = 'Chase'
    mapping = {
        'make_payment': f'Make a payment: {org}',
        'review_legal': f'Review legal filing: {org}',
        'review_doc': f'Review document: {org}',
        'respond_msg': f'Respond to message: {org}',
        'confirm_appt': f'Confirm appointment: {org}',
        'submit_form': f'Submit form: {org}',
        'upload_doc': f'Upload document: {org}',
        'follow_up': f'Follow up with: {org}',
    }
    return mapping.get(kind, f'Respond to message: {org}')[:140]

def infer_due_date(subject, body, email_dt):
    text = lower_text(subject, body)
    if re.search(r'\b(today|asap|urgent|immediately|past due|overdraft|low balance)\b', text):
        return email_dt.date().isoformat()
    m = re.search(r'\bby\s+([A-Z][a-z]+\s+\d{1,2}(?:,\s*\d{4})?)', (subject or '') + ' ' + (body or ''))
    if m:
        raw = m.group(1)
        for fmt in ('%B %d, %Y', '%B %d'):
            try:
                d = dt.datetime.strptime(raw, fmt)
                year = d.year if '%Y' in fmt else email_dt.year
                return dt.date(year, d.month, d.day).isoformat()
            except Exception:
                pass
    return None

def priority_for(kind, subject, body):
    text = lower_text(subject, body)
    if kind == 'make_payment' and re.search(r'\b(overdraft|past due|autopay failed|insufficient funds)\b', text):
        return 1
    if kind in ('review_legal', 'confirm_appt'):
        return 1
    return 2

def has_noise_markers(subject, body, from_header, snippet=''):
    low = lower_text(subject, snippet, (body or '')[:1000], from_header)
    if any(p in low for p in NOISE_SENDER_PATTERNS) and not re.search(r'\b(confirm|required|due|pay|reply|respond|complete|submit|upload|send)\b', low):
        return True
    if any(p in low for p in MARKETING_HINTS):
        return True
    if any(p in low for p in STATUS_ONLY_PHRASES):
        return True
    return False

def resolution_in_text(subject, body):
    low = lower_text(subject, body)
    return any(w in low for w in RESOLUTION_WORDS)

def summarize(text):
    t = re.sub(r'\s+', ' ', text or '').strip()
    t = re.sub(r'On .* wrote:.*$', '', t, flags=re.I)
    return t[:400]

gconn = sqlite3.connect(GOOGLE_DB)
gconn.row_factory = sqlite3.Row
row = gconn.execute("SELECT t.access_token FROM oauth_tokens t JOIN connections c ON c.id=t.connection_id WHERE c.id='google:personal'").fetchone()
if not row:
    print(json.dumps({'error': 'missing google:personal token'}))
    sys.exit(1)
token = row['access_token']

adb = sqlite3.connect(ADMIN_DB, timeout=60)
adb.row_factory = sqlite3.Row
adb.execute("PRAGMA busy_timeout=60000")
messages = list_messages(token)
thread_ids, seen = [], set()
for m in messages:
    tid = m.get('threadId')
    if tid and tid not in seen:
        seen.add(tid)
        thread_ids.append(tid)

scanned = inserted = 0
skip_reasons = {}
inserted_rows = []
finance_groups = {}

for tid in thread_ids:
    scanned += 1
    try:
        thread = get_thread(tid, token)
    except Exception:
        skip_reasons['thread_fetch_failed'] = skip_reasons.get('thread_fetch_failed', 0) + 1
        continue
    msgs = []
    for msg in thread.get('messages') or []:
        headers = header_map((msg.get('payload') or {}).get('headers') or [])
        frm = headers.get('from', '')
        subj = headers.get('subject', '')
        sender_name, sender_email = clean_sender(frm)
        try:
            email_dt = dt.datetime.fromtimestamp(int(msg.get('internalDate'))/1000.0, tz=dt.timezone.utc)
        except Exception:
            email_dt = dt.datetime.now(dt.timezone.utc)
        body = extract_text_from_payload(msg.get('payload') or {})
        msgs.append({'id': msg.get('id'), 'thread_id': tid, 'from': frm, 'sender_name': sender_name, 'sender_email': sender_email, 'subject': subj, 'body': body, 'email_dt': email_dt, 'snippet': msg.get('snippet', ''), 'is_user': sender_email == USER_EMAIL})
    msgs.sort(key=lambda x: x['email_dt'])
    inbound = [m for m in msgs if not m['is_user']]
    if not inbound:
        skip_reasons['no_inbound'] = skip_reasons.get('no_inbound', 0) + 1
        continue
    latest = inbound[-1]
    text = lower_text(latest['subject'], latest['body'], latest['snippet'])
    if has_noise_markers(latest['subject'], latest['body'], latest['from'], latest['snippet']):
        skip_reasons['noise_or_marketing'] = skip_reasons.get('noise_or_marketing', 0) + 1
        continue
    action_kind = classify_action(latest['subject'], latest['body'], latest['sender_name'], latest['sender_email'], latest['snippet'])
    if not action_kind:
        skip_reasons['no_clear_action'] = skip_reasons.get('no_clear_action', 0) + 1
        continue
    if APPOINTMENT_WORDS.search(text) and not re.search(r'\b(confirm|required|complete forms|paperwork|check in|reply)\b', text):
        skip_reasons['appointment_info_only'] = skip_reasons.get('appointment_info_only', 0) + 1
        continue
    if resolution_in_text(latest['subject'], latest['body']):
        skip_reasons['already_resolved_inbound'] = skip_reasons.get('already_resolved_inbound', 0) + 1
        continue
    actionable_ts = latest['email_dt']
    resolved = False
    for later in msgs:
        if later['email_dt'] <= actionable_ts:
            continue
        if later['is_user'] and action_kind in ('respond_msg', 'follow_up', 'submit_form', 'upload_doc', 'confirm_appt'):
            resolved = True
            break
        if resolution_in_text(later['subject'], later['body']):
            resolved = True
            break
    if resolved:
        skip_reasons['resolved_in_thread'] = skip_reasons.get('resolved_in_thread', 0) + 1
        continue
    if adb.execute("SELECT 1 FROM tasks WHERE gmail_message_id=? LIMIT 1", (latest['id'],)).fetchone():
        skip_reasons['duplicate_message_id'] = skip_reasons.get('duplicate_message_id', 0) + 1
        continue
    if adb.execute("SELECT 1 FROM tasks WHERE json_extract(source_details,'$.thread_id')=? AND status='open' LIMIT 1", (tid,)).fetchone():
        skip_reasons['open_task_same_thread'] = skip_reasons.get('open_task_same_thread', 0) + 1
        continue
    title = normalized_title(action_kind, latest['sender_name'], latest['sender_email'], latest['subject'], latest['body'])
    if adb.execute("SELECT 1 FROM tasks WHERE source='gmail' AND status='open' AND title=? AND json_extract(source_details,'$.from')=? AND datetime(created_at) >= datetime('now','-10 days') LIMIT 1", (title, latest['from'])).fetchone():
        skip_reasons['similar_open_task_same_sender'] = skip_reasons.get('similar_open_task_same_sender', 0) + 1
        continue
    if action_kind == 'make_payment':
        score = 3 if re.search(r'\b(overdraft|insufficient funds)\b', text) else 2 if re.search(r'\b(past due|autopay failed|balance due)\b', text) else 1
        key = (latest['sender_email'] or latest['from'], latest['email_dt'].date().isoformat())
        cand = {'score': score, 'latest': latest, 'title': title, 'description': summarize(latest['body'] or latest['snippet']), 'due_date': infer_due_date(latest['subject'], latest['body'], latest['email_dt']), 'priority': priority_for(action_kind, latest['subject'], latest['body'])}
        prev = finance_groups.get(key)
        if not prev or score > prev['score']:
            if prev:
                skip_reasons['weaker_finance_alert'] = skip_reasons.get('weaker_finance_alert', 0) + 1
            finance_groups[key] = cand
        else:
            skip_reasons['weaker_finance_alert'] = skip_reasons.get('weaker_finance_alert', 0) + 1
        continue
    src = json.dumps({'subject': clean_subject(latest['subject']), 'from': latest['from'], 'email_date': latest['email_dt'].isoformat(), 'thread_id': tid})
    adb.execute("INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) VALUES (?,?,?,?, 'open','gmail',?,?)", (title, summarize(latest['body'] or latest['snippet']), infer_due_date(latest['subject'], latest['body'], latest['email_dt']), priority_for(action_kind, latest['subject'], latest['body']), latest['id'], src))
    inserted += 1
    inserted_rows.append({'title': title, 'message_id': latest['id']})

for cand in finance_groups.values():
    latest = cand['latest']
    if adb.execute("SELECT 1 FROM tasks WHERE gmail_message_id=? LIMIT 1", (latest['id'],)).fetchone():
        skip_reasons['duplicate_message_id'] = skip_reasons.get('duplicate_message_id', 0) + 1
        continue
    if adb.execute("SELECT 1 FROM tasks WHERE json_extract(source_details,'$.thread_id')=? AND status='open' LIMIT 1", (latest['thread_id'],)).fetchone():
        skip_reasons['open_task_same_thread'] = skip_reasons.get('open_task_same_thread', 0) + 1
        continue
    if adb.execute("SELECT 1 FROM tasks WHERE source='gmail' AND status='open' AND title=? AND json_extract(source_details,'$.from')=? AND datetime(created_at) >= datetime('now','-10 days') LIMIT 1", (cand['title'], latest['from'])).fetchone():
        skip_reasons['similar_open_task_same_sender'] = skip_reasons.get('similar_open_task_same_sender', 0) + 1
        continue
    src = json.dumps({'subject': clean_subject(latest['subject']), 'from': latest['from'], 'email_date': latest['email_dt'].isoformat(), 'thread_id': latest['thread_id']})
    adb.execute("INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) VALUES (?,?,?,?, 'open','gmail',?,?)", (cand['title'], cand['description'], cand['due_date'], cand['priority'], latest['id'], src))
    inserted += 1
    inserted_rows.append({'title': cand['title'], 'message_id': latest['id']})

adb.commit()
print(json.dumps({'scanned_count': scanned, 'inserted_count': inserted, 'inserted': inserted_rows, 'skipped_reasons': dict(sorted(skip_reasons.items()))}, ensure_ascii=False))
