import base64, datetime as dt, email.utils, html, json, os, re, sqlite3, subprocess, sys
from collections import Counter, defaultdict

GOOGLE_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
USER_EMAILS = {'cbadcock@gmail.com', 'corey@pivotvia.com'}
QUERY = 'category:primary in:inbox newer_than:4d -category:promotions -category:social'
NOW = dt.datetime.utcnow()

STRONG_ACTION_PATTERNS = [
    r'\bplease (reply|respond|confirm|review|sign|submit|send|upload|complete|advise|let me know)\b',
    r'\b(action required|required action|response required)\b',
    r'\b(balance due|payment due|past due|amount due|overdue|make a payment)\b',
    r'\b(please review|please sign|please complete|please submit|please upload)\b',
    r'\b(need you to|we need you to|you need to|must)\b',
    r'\b(confirm your appointment|confirm appointment|secure message)\b',
    r'\b(upload (a|an|the)? ?document|submit (a|an|the)? ?form|send (us )?(the )?(information|document))\b',
    r'\bdeadline\b',
]
WEAK_ACTION_PATTERNS = [
    r'\bnew message waiting\b',
    r'\byou have received a document\b',
    r'\bnew order\(s\) have been filed\b',
    r'\bplease take a moment to review\b',
    r'\bplease log in to review\b',
]
NO_ACTION_PATTERNS = [
    r'\b(receipt|payment receipt|refund is confirmed|refund confirmation)\b',
    r'\b(cancelled|canceled|successfully cancelled|membership has been cancelled|subscription canceled)\b',
    r'\b(final confirmation|confirmation only|you are confirmed|see you then|sounds good|thanks got it)\b',
    r'\b(we\'ll send you an update|we are on it|keep an eye out|will provide an update|we weren\'t able to locate it)\b',
    r'\b(status update|automatic reply|out of office|on leave|for immediate concerns)\b',
    r'\b(sign in from a new device|security alert|verification code)\b',
    r'\b(statement is available|eDelivery Notification)\b',
    r'\b(newsletter|unsubscribe|manage preferences)\b',
    r'\b(invitation for telehealth appointment)\b',
]
RESOLVED_PATTERNS = [
    r'\b(confirmed|filed|extension filed|done|completed|taken care of|scheduled|sounds good|see you then|paid|submitted|thanks[,]? got it|processed your refund|membership has been cancelled|successfully cancelled)\b'
]
OPEN_SIMILAR_DAYS = 10


def sh_json(url: str, token: str):
    out = subprocess.check_output(['curl', '-s', '-H', f'Authorization: Bearer {token}', url])
    return json.loads(out)


def get_access_token():
    conn = sqlite3.connect(GOOGLE_DB)
    row = conn.execute("select access_token from oauth_tokens where connection_id='google:personal'").fetchone()
    if not row or not row[0]:
        raise SystemExit('missing_access_token')
    return row[0]


def parse_headers(msg):
    return {h['name'].lower(): h['value'] for h in msg.get('payload', {}).get('headers', [])}


def decode_body(payload):
    texts = []
    def walk(part):
        mime = (part.get('mimeType') or '').lower()
        body = part.get('body', {})
        data = body.get('data')
        if data and mime.startswith(('text/plain', 'text/html')):
            try:
                txt = base64.urlsafe_b64decode(data + '===').decode('utf-8', 'ignore')
            except Exception:
                txt = ''
            if mime.startswith('text/html'):
                txt = re.sub(r'(?is)<(script|style).*?>.*?</\1>', ' ', txt)
                txt = re.sub(r'(?i)<br\s*/?>', '\n', txt)
                txt = re.sub(r'(?i)</p>|</div>|</li>|</tr>', '\n', txt)
                txt = re.sub(r'(?s)<[^>]+>', ' ', txt)
            txt = html.unescape(txt)
            txt = re.sub(r'\s+', ' ', txt).strip()
            if txt:
                texts.append(txt)
        for child in part.get('parts', []) or []:
            walk(child)
    walk(payload)
    joined = ' '.join(texts)
    return re.sub(r'\s+', ' ', joined).strip()


def parse_date(s):
    try:
        return email.utils.parsedate_to_datetime(s)
    except Exception:
        return None


def extract_email(from_header: str):
    return (email.utils.parseaddr(from_header)[1] or '').lower()


def sender_org(from_header: str):
    name, addr = email.utils.parseaddr(from_header)
    base = name or addr.split('@')[0]
    base = re.sub(r'(?i)^(re|fwd?)\s*:\s*', '', base).strip('" ')
    if '@' in addr:
        domain = addr.split('@', 1)[1].lower()
        parts = [p for p in domain.split('.') if p not in {'com','org','net','edu','gov','co','us','mail','mg','s','usa'}]
        if (not base) or 'noreply' in base.lower() or len(base) < 3:
            base = ' '.join(p.capitalize() for p in parts[:2]) or addr
    base = re.sub(r'\s+', ' ', base).strip()
    return base[:80] if base else addr


def clean_subject(subject: str):
    return re.sub(r'(?i)^(re|fw|fwd)\s*:\s*', '', subject or '').strip()


def description_from_text(text: str):
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:280] if text else None


def infer_due_date(text: str, email_dt):
    text_l = text.lower()
    if 'today' in text_l and email_dt:
        return email_dt.date().isoformat()
    if 'tomorrow' in text_l and email_dt:
        return (email_dt.date() + dt.timedelta(days=1)).isoformat()
    m = re.search(r'\b(?:due|by|before)\s+(?:on\s+)?([A-Z][a-z]{2,9}\s+\d{1,2}(?:,\s*\d{4})?)', text)
    if m:
        raw = m.group(1)
        for fmt in ('%B %d, %Y', '%b %d, %Y', '%B %d', '%b %d'):
            try:
                d = dt.datetime.strptime(raw, fmt)
                year = d.year if '%Y' in fmt else (email_dt.year if email_dt else NOW.year)
                return d.replace(year=year).date().isoformat()
            except Exception:
                pass
    return None


def priority_for(title, text):
    t = f'{title} {text}'.lower()
    if any(k in t for k in ['payment', 'past due', 'overdue', 'legal', 'court', 'deadline', 'appointment']):
        return 1
    return 2


def normalize_title(subject, from_header, text):
    subj = clean_subject(subject)
    org = sender_org(from_header)
    low = f'{subj} {text}'.lower()
    if any(k in low for k in ['balance due','payment due','past due','make a payment','overdue','amount due']):
        return f'Make a payment: {org}'
    if any(k in low for k in ['order filed','orders filed','court','legal filing','case ', 'respondent\'s counsel']):
        return f'Review legal filing: {org}'
    if any(k in low for k in ['secure message','message waiting']) or ('please reply' in low or 'please respond' in low):
        return f'Respond to message: {org}'
    if any(k in low for k in ['confirm your appointment','confirm appointment']):
        return f'Confirm appointment: {org}'
    if any(k in low for k in ['submit form','complete form','fill out']) :
        return f'Submit form: {org}'
    if any(k in low for k in ['upload document','upload a document']):
        return f'Upload document: {org}'
    if any(k in low for k in ['send information','send us the information','send the information']):
        return f'Send information: {org}'
    if any(k in low for k in ['document','review']) or any(k in subj.lower() for k in ['document', 'edelivery', 'statement']):
        return f'Review document: {org}'
    return f'Follow up with: {org}'


def match_any(patterns, text):
    return any(re.search(p, text, re.I) for p in patterns)


def similar_key(title):
    title = title.lower()
    title = re.sub(r':.*', '', title)
    return title.strip()


def candidate_actionable(msg, thread_msgs):
    headers = parse_headers(msg)
    from_header = headers.get('from', '')
    subject = headers.get('subject', '')
    email_dt = parse_date(headers.get('date', ''))
    body = decode_body(msg.get('payload', {}))
    snippet = html.unescape(msg.get('snippet', ''))
    text = re.sub(r'\s+', ' ', f'{subject} {snippet} {body}').strip()
    low = text.lower()

    if match_any(NO_ACTION_PATTERNS, low):
        return None, 'no_action_notification'
    if any(k in low for k in ['lost and found', 'we found', 'we were not able to locate']):
        return None, 'lost_and_found_or_status'
    if ('telehealth' in low or 'video visit' in low or 'appointment starts' in low or 'starts in approximately' in low) and not any(k in low for k in ['confirm appointment', 'please confirm', 'action required']):
        return None, 'appointment_info_only'
    if 'you do not need to download anything or do anything to prepare' in low or "you don't need to download anything or do anything to prepare" in low:
        return None, 'appointment_info_only'

    later = []
    msg_dt = int(msg.get('internalDate', '0') or 0)
    for other in thread_msgs:
        if int(other.get('internalDate', '0') or 0) > msg_dt:
            later.append(other)

    reply_needed = match_any(STRONG_ACTION_PATTERNS, low) or any(k in low for k in ['please advise', 'let me know', 'what works'])
    for other in later:
        oh = parse_headers(other)
        other_from = extract_email(oh.get('from', ''))
        other_text = re.sub(r'\s+', ' ', f"{oh.get('subject','')} {html.unescape(other.get('snippet',''))} {decode_body(other.get('payload', {}))}").lower()
        if other_from in USER_EMAILS and reply_needed:
            return None, 'resolved_by_later_user_reply'
        if other_from not in USER_EMAILS and match_any(RESOLVED_PATTERNS, other_text):
            return None, 'resolved_by_later_inbound'

    strong = match_any(STRONG_ACTION_PATTERNS, low)
    weak = match_any(WEAK_ACTION_PATTERNS, low)
    if not strong and not weak:
        return None, 'no_explicit_action'

    # Conservative downgrade for automated FYI-style messages
    if weak and any(k in low for k in ['notification', 'message waiting', 'document']) and not any(k in low for k in ['please review', 'action required', 'please sign', 'please complete']):
        return None, 'weak_review_signal_only'

    title = normalize_title(subject, from_header, text)
    details = {
        'subject': subject,
        'from': from_header,
        'email_date': headers.get('date', ''),
        'thread_id': msg.get('threadId'),
    }
    return {
        'title': title,
        'description': description_from_text(snippet or body),
        'due_date': infer_due_date(text, email_dt),
        'priority': priority_for(title, text),
        'gmail_message_id': msg['id'],
        'source_details': json.dumps(details),
        'sender_email': extract_email(from_header),
        'sender_org': sender_org(from_header),
        'email_dt': email_dt.isoformat() if email_dt else None,
        'text': text,
    }, None


def main():
    token = get_access_token()
    admin = sqlite3.connect(ADMIN_DB)
    admin.row_factory = sqlite3.Row
    existing_ids = {r['gmail_message_id'] for r in admin.execute("select gmail_message_id from tasks where gmail_message_id is not null")}
    recent_open = [dict(r) for r in admin.execute(
        "select id, title, source_details, created_at from tasks where status='open' and created_at >= datetime('now', ?) ",
        (f'-{OPEN_SIMILAR_DAYS} days',)
    )]

    url = f'https://gmail.googleapis.com/gmail/v1/users/me/messages?q={QUERY.replace(" ", "%20")}&maxResults=100'
    messages = []
    while url:
        data = sh_json(url, token)
        messages.extend(data.get('messages', []))
        npt = data.get('nextPageToken')
        url = f'https://gmail.googleapis.com/gmail/v1/users/me/messages?q={QUERY.replace(" ", "%20")}&maxResults=100&pageToken={npt}' if npt else None

    scanned = len(messages)
    skip = Counter()
    inserts = []
    finance_groups = defaultdict(list)

    for item in messages:
        mid = item['id']
        if mid in existing_ids:
            skip['duplicate_gmail_message_id'] += 1
            continue
        meta = sh_json(f'https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date', token)
        thread = sh_json(f'https://gmail.googleapis.com/gmail/v1/users/me/threads/{meta["threadId"]}?format=full', token)
        target = None
        for m in thread.get('messages', []):
            if m['id'] == mid:
                target = m
                break
        if not target:
            skip['thread_lookup_failed'] += 1
            continue
        result, reason = candidate_actionable(target, thread.get('messages', []))
        if not result:
            skip[reason] += 1
            continue

        # skip if similar recent open task from same sender and same action family
        sim = False
        for t in recent_open:
            sd = t['source_details']
            try:
                sdj = json.loads(sd) if sd else {}
            except Exception:
                sdj = {}
            same_sender = (sdj.get('from') and result['sender_org'].lower() in sdj.get('from', '').lower()) or (result['sender_email'] and result['sender_email'] in (sdj.get('from','').lower()))
            if same_sender and similar_key(t['title']) == similar_key(result['title']):
                sim = True
                break
        if sim:
            skip['similar_recent_open_task'] += 1
            continue

        low = result['text'].lower()
        if any(k in low for k in ['overdraft', 'low balance', 'negative balance']):
            sev = 3 if 'overdraft' in low or 'negative balance' in low else 2
            day = (result['email_dt'] or '')[:10]
            finance_groups[(result['sender_org'], day)].append((sev, result))
            continue

        inserts.append(result)

    # finance escalation: keep strongest per sender/day
    for grp in finance_groups.values():
        grp.sort(key=lambda x: x[0], reverse=True)
        inserts.append(grp[0][1])
        for _ in grp[1:]:
            skip['weaker_finance_alert_superseded'] += 1

    inserted = 0
    inserted_titles = []
    for r in inserts:
        admin.execute(
            "insert into tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) values (?, ?, ?, ?, 'open', 'gmail', ?, ?)",
            (r['title'], r['description'], r['due_date'], r['priority'], r['gmail_message_id'], r['source_details'])
        )
        inserted += 1
        inserted_titles.append(r['title'])
    admin.commit()

    print(f'scanned={scanned}')
    print(f'inserted={inserted}')
    if inserted_titles:
        print('inserted_titles=' + json.dumps(inserted_titles, ensure_ascii=False))
    summary = {k:v for k,v in skip.most_common()}
    print('skipped=' + json.dumps(summary, ensure_ascii=False))

if __name__ == '__main__':
    main()
