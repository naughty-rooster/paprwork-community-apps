import sqlite3, json, re
from datetime import timezone
from email.utils import parsedate_to_datetime

GOOGLE_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'

SKIP_PHRASES = [
    'will provide an update', 'keep an eye out', "weren't able to locate it",
    'we were not able to locate it', 'sounds good', 'see you then', 'thanks got it',
    'taken care of', 'already scheduled', 'your payment is scheduled', 'payment confirmation'
]
RESOLVED_KEYWORDS = [
    'confirmed','filed','extension filed','done','completed','taken care of','scheduled',
    'sounds good','see you then','paid','submitted','thanks got it','refund is confirmed',
    'successfully cancelled','cancellation confirmation'
]
NOISE_SENDERS = {'info@email.meetup.com'}
NOISE_PATTERNS = [
    r'\bpromoted by\b', r'\bnewsletter\b', r'\bsmartbrief\b', r'\bsubscription cancellation\b',
    r'\bverify your account\b', r'\bsecurity alert\b', r'\bmailbox linked\b', r'\bwelcome to\b'
]
ACTION_PATTERNS = [
    (r'\bpay\b|\boverdrawn\b|\bpast due\b|\bbalance due\b|\bdue now\b|\bmake a payment\b', 'Make a payment'),
    (r'\bupload\b.*\bdocument\b|\bsend\b.*\bdocument\b|\battach\b.*\bdocument\b', 'Upload document'),
    (r'\bsubmit\b.*\bform\b|\bcomplete\b.*\bform\b|\bfill out\b', 'Submit form'),
    (r'\breview\b.*\bdocument\b|\bdocument\s+from\b', 'Review document'),
    (r'\blegal filing\b|\borders filed\b|\bfiling\b', 'Review legal filing'),
    (r'\bconfirm\b.*\bappointment\b|\bconfirm your appointment\b|\btelehealth appointment\b', 'Confirm appointment'),
    (r'\bsecure message\b|\bplease reply\b|\bcan you\b|\bcould you\b|\bneed you to\b|\bwould you\b', 'Respond to message'),
    (r'\bsend\b.*\binformation\b|\bprovide\b.*\binformation\b', 'Send information'),
]

EMAIL_RE = re.compile(r'<([^>]+)>')
NAME_PREFIX_RE = re.compile(r'^(re:|fwd?:|hello\s+corey[:,]?|invitation for)', re.I)


def parse_email_date(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def extract_sender(from_hdr):
    if not from_hdr:
        return '', ''
    m = EMAIL_RE.search(from_hdr)
    email = (m.group(1) if m else from_hdr).strip().strip('"').lower()
    name = from_hdr.replace(f'<{m.group(1)}>', '').strip(' "') if m else email
    if not name or name == email:
        name = email.split('@')[0]
    return name, email


def norm_space(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


def human_org(name, email):
    if name and '@' not in name and len(name) > 2:
        return name
    local = email.split('@')[0] if email else ''
    domain = email.split('@')[-1] if '@' in email else ''
    if domain:
        parts = domain.split('.')
        if len(parts) >= 2:
            base = parts[-2]
            return base.replace('-', ' ').replace('_', ' ').title()
    return local.replace('.', ' ').title() if local else 'Sender'


def classify(subject, body, from_name, from_email):
    text = norm_space(' '.join([subject or '', body or ''])).lower()
    if from_email in NOISE_SENDERS:
        return None, 'newsletter/marketing'
    if any(p in text for p in SKIP_PHRASES):
        return None, 'status/reassurance only'
    for pat in NOISE_PATTERNS:
        if re.search(pat, text):
            return None, 'notification/marketing'
    if 'if this change was unexpected' in text and 'mailbox linked' in text:
        return None, 'conditional security notice; no explicit action'
    if 'inviting you to a scheduled zoom meeting' in text or 'join zoom meeting' in text:
        return None, 'meeting invite/reminder only'
    if 'assuming this isn’t a priority' in text or "assuming this isn't a priority" in text:
        return None, 'soft close / no ask'
    if 'happy to reconnect' in text and 'if' in text:
        return None, 'no explicit ask'
    label = None
    for pat, action in ACTION_PATTERNS:
        if re.search(pat, text):
            label = action
            break
    if not label:
        return None, 'no explicit action'
    org = human_org(from_name, from_email)
    title = f'{label}: {org}'
    if NAME_PREFIX_RE.search(title):
        title = re.sub(NAME_PREFIX_RE, '', title).strip()
    return title, None


def priority_for(title, body):
    text = norm_space(' '.join([title or '', body or ''])).lower()
    if any(k in text for k in ['overdrawn','past due','due now','urgent']):
        return 1
    if any(k in text for k in ['payment','confirm','submit','upload','legal filing']):
        return 2
    return 2


def similar_open_task_exists(aconn, sender_email, title):
    row = aconn.execute(
        """
        SELECT id FROM tasks
        WHERE status='open' AND source='gmail'
          AND created_at >= datetime('now','-14 days')
          AND lower(coalesce(json_extract(source_details,'$.from'),'')) LIKE '%' || lower(?) || '%'
          AND lower(title) = lower(?)
        LIMIT 1
        """,
        (sender_email, title)
    ).fetchone()
    return bool(row)


def later_resolved(thread_rows):
    if not thread_rows:
        return False
    for r in thread_rows[1:]:
        text = norm_space(' '.join([r['subject'], r['body'], r['summary']])).lower()
        if r['direction'] == 'outbound':
            return True
        if any(k in text for k in RESOLVED_KEYWORDS):
            return True
    return False


gconn = sqlite3.connect(GOOGLE_DB)
gconn.row_factory = sqlite3.Row
aconn = sqlite3.connect(ADMIN_DB)
aconn.row_factory = sqlite3.Row

connection_id = 'google:personal'
row = gconn.execute("SELECT count(*) c FROM activities WHERE connection_id=? AND activity_type='email'", (connection_id,)).fetchone()
if row['c'] == 0:
    connection_id = 'google:primary'

max_ts = gconn.execute("SELECT max(occurred_at) m FROM activities WHERE connection_id=? AND activity_type='email'", (connection_id,)).fetchone()['m']
if not max_ts:
    print('scanned=0 inserted=0 skipped=no_email_data')
    raise SystemExit(0)

recent = gconn.execute(
    """
    SELECT external_id gmail_message_id, occurred_at, summary, body_text, direction, raw_payload
    FROM activities
    WHERE connection_id=? AND activity_type='email'
      AND occurred_at >= datetime(?, '-4 days')
    ORDER BY occurred_at DESC
    """,
    (connection_id, max_ts)
).fetchall()

scanned = 0
inserted = 0
skip_reasons = {}
insert_rows = []

for row in recent:
    payload = json.loads(row['raw_payload'])
    labels = payload.get('labelIds', [])
    if 'INBOX' not in labels:
        continue
    if 'CATEGORY_PROMOTIONS' in labels or 'CATEGORY_SOCIAL' in labels:
        continue

    scanned += 1
    headers = payload.get('headers', {})
    subject = headers.get('subject', '')
    from_hdr = headers.get('from', '')
    email_date = headers.get('date', '')
    thread_id = payload.get('threadId')
    from_name, from_email = extract_sender(from_hdr)

    dup = aconn.execute("SELECT id FROM tasks WHERE gmail_message_id=? LIMIT 1", (row['gmail_message_id'],)).fetchone()
    if dup:
        skip_reasons['duplicate_message_id'] = skip_reasons.get('duplicate_message_id', 0) + 1
        continue

    thread_rows = []
    if thread_id:
        trows = gconn.execute(
            """
            SELECT occurred_at, direction, summary, body_text body, raw_payload
            FROM activities
            WHERE connection_id=? AND activity_type='email' AND json_extract(raw_payload,'$.threadId')=?
            ORDER BY occurred_at
            """,
            (connection_id, thread_id)
        ).fetchall()
        for tr in trows:
            p = json.loads(tr['raw_payload'])
            hh = p.get('headers', {})
            thread_rows.append({
                'occurred_at': tr['occurred_at'],
                'direction': tr['direction'],
                'summary': tr['summary'] or '',
                'body': tr['body'] or '',
                'subject': hh.get('subject', ''),
            })

    if later_resolved(thread_rows):
        skip_reasons['thread_resolved'] = skip_reasons.get('thread_resolved', 0) + 1
        continue

    title, why_skip = classify(subject, row['body_text'] or row['summary'] or '', from_name, from_email)
    if why_skip:
        skip_reasons[why_skip] = skip_reasons.get(why_skip, 0) + 1
        continue

    if similar_open_task_exists(aconn, from_email, title):
        skip_reasons['similar_open_task'] = skip_reasons.get('similar_open_task', 0) + 1
        continue

    description = norm_space((row['summary'] or row['body_text'] or '')[:500])
    prio = priority_for(title, row['body_text'] or '')
    source_details = json.dumps({
        'subject': subject,
        'from': from_hdr,
        'email_date': email_date or row['occurred_at'],
        'thread_id': thread_id,
    })
    insert_rows.append((title, description, None, prio, 'gmail', row['gmail_message_id'], source_details))

for vals in insert_rows:
    aconn.execute(
        """
        INSERT INTO tasks (title, description, due_date, priority, source, gmail_message_id, source_details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        vals
    )
    inserted += 1
aconn.commit()

parts = [f'scanned={scanned}', f'inserted={inserted}', f'connection={connection_id}']
if skip_reasons:
    parts.append('skipped=' + ', '.join(f'{k}:{v}' for k, v in sorted(skip_reasons.items())))
print(' '.join(parts))
for vals in insert_rows:
    print('inserted_title=' + vals[0])
