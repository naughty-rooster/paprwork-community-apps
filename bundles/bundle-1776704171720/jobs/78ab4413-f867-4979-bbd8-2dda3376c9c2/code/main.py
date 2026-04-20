import json, os, re, sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import requests

ADMIN_DB = "/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db"
BASE = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
SID = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
PHONE = os.environ.get('TWILIO_PHONE_NUMBER', '').strip()
PREFIX_RE = re.compile(r'^\s*(task|todo|reminder|add task)\b\s*[:\-]?\s*', re.I)
OTP_RE = re.compile(r'(verification code|security code|one[- ]time|passcode|never ask for this code|2fa|auth code)', re.I)
MARKETING_RE = re.compile(r'(sale|promo|offer ends|reward points|unsubscribe|reply stop)', re.I)
RECEIPT_RE = re.compile(r'(track your delivery|order .* shipped|order is ready|view your receipt)', re.I)
AUTO_IGNORE_RE = re.compile(r'(do not reply|reply stop|msg&data rates|text stop|autopay is scheduled)', re.I)
SCHEDULE_REQ_RE = re.compile(r'(time to schedule|schedule your follow up|schedule .* appointment|book .* appointment)', re.I)
APPT_RE = re.compile(r'(appointment|appointment reminder|appointment is confirmed|confirmed for|scheduled for|see you on|virtual appointment|starts at)', re.I)
HUMAN_ASK_RE = re.compile(r'(can you|could you|will you|please|wanted to confirm|do you want|are you available)', re.I)
ADMIN_TASK_RE = re.compile(r'(invoice|statement|balance due|past due|pay online|payment|paperwork|claim|form|survey|documents?|extension filed|efile|tax|child support|green card|citizenship)', re.I)
MEDICAL_TASK_RE = re.compile(r'(rx|prescription|pharmacy|ready for pick up|ready for pickup|therapy|dentist|neurologist|provider|clinic|medical|premera)', re.I)
LOCATION_RE = re.compile(r'(?:\bat\b|location:?|address:?)([^\n\.]+)', re.I)
DURATION_RE = re.compile(r'\b(\d{2,3})\s*(?:min|minutes?)\b', re.I)
DAY_RE = re.compile(r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)', re.I)
TIME_RE = re.compile(r'\b(\d{1,2}:\d{2}\s*[ap]m)\b', re.I)
BADGE_MAP = {'medical-admin':0.96,'personal-admin':0.9,'family-logistics':0.55}


def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS message_candidates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_guid TEXT NOT NULL UNIQUE,
      chat_identifier TEXT,
      contact TEXT,
      message_text TEXT NOT NULL,
      message_date TEXT,
      score REAL DEFAULT 0,
      status TEXT DEFAULT 'new',
      source_details TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_message_candidates_status ON message_candidates(status);
    CREATE INDEX IF NOT EXISTS idx_message_candidates_date ON message_candidates(message_date);
    """)


def clean_text(text):
    return re.sub(r'\s+', ' ', (text or '').replace('\uFFFC', ' ')).strip(' :\n\t\r')


def task_title(text):
    cleaned = clean_text(PREFIX_RE.sub('', text or ''))
    cleaned = re.sub(r'\b(today|tonight|tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b', '', cleaned, flags=re.I)
    return re.sub(r'\s+', ' ', cleaned).strip(' ,-')[:120] or 'Task from SMS'


def parse_due_date(text, now):
    lower = (text or '').lower()
    if any(x in lower for x in ['today', 'tonight']):
        return now.date().isoformat()
    if 'tomorrow' in lower:
        return (now.date() + timedelta(days=1)).isoformat()
    m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', lower)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100: year += 2000
        try:
            d = datetime(year, month, day).date()
            return d.isoformat()
        except ValueError:
            return None
    return None


def priority_for(text, due_date, now):
    lower = (text or '').lower()
    if any(x in lower for x in ['urgent', 'asap', 'immediately']) or lower.count('!') >= 2:
        return 1
    if due_date == now.date().isoformat():
        return 1
    if any(x in lower for x in ['tomorrow', 'this week', 'soon', 'important', 'balance due', 'past due']):
        return 2
    return 3


def parse_appt_datetime(text, now):
    txt = text.replace('(PT)', '')
    patterns = [
        '%A, %B %d %I:%M%p', '%a, %b %d %I:%M%p', '%B %d %I:%M%p', '%b %d %I:%M%p'
    ]
    m = re.search(r'([A-Za-z]{3,9},?\s+[A-Za-z]{3,9}\s+\d{1,2})[^\d]*(\d{1,2}:\d{2}\s*[APMapm]{2})', txt)
    if not m:
        m = re.search(r'([A-Za-z]{3,9}\s+\d{1,2})[^\d]*(\d{1,2}:\d{2}\s*[APMapm]{2})', txt)
    if not m:
        return None, None
    ds = m.group(1).replace(',', '')
    ts = m.group(2).upper().replace(' ', '')
    for fmt in patterns:
        try:
            dt = datetime.strptime(f'{ds} {ts}', fmt).replace(year=now.year)
            if dt.date() < now.date() - timedelta(days=2):
                dt = dt.replace(year=now.year + 1)
            return dt.date().isoformat(), dt.strftime('%I:%M %p').lstrip('0')
        except ValueError:
            pass
    return None, None


def classify_message(text, when):
    lower = (text or '').lower()
    if not text or len(text) < 4:
        return {'kind':'ignore','reason':'empty','category':'noise'}
    if OTP_RE.search(lower) or MARKETING_RE.search(lower) or RECEIPT_RE.search(lower) or AUTO_IGNORE_RE.search(lower):
        return {'kind':'ignore','reason':'noise','category':'noise'}
    if APPT_RE.search(lower) and (DAY_RE.search(lower) or TIME_RE.search(lower)):
        event_date, starts_at = parse_appt_datetime(text, when)
        if event_date and starts_at:
            loc = None
            lm = LOCATION_RE.search(text)
            if lm: loc = clean_text(lm.group(1))[:160]
            dm = DURATION_RE.search(lower)
            mins = int(dm.group(1)) if dm else 60
            title = 'Appointment'
            if 'david shen' in lower or 'shen-miller' in lower:
                title = 'David Shen-Miller appointment'
            elif 'therapy' in lower:
                title = 'Therapy appointment'
            elif 'dentist' in lower:
                title = 'Dentist appointment'
            return {'kind':'calendar','reason':'appointment','category':'calendar','event_date':event_date,'starts_at':starts_at,'location':loc,'duration_minutes':mins,'title':title,'notes':text[:300]}
    if SCHEDULE_REQ_RE.search(lower):
        cat = 'medical-admin' if MEDICAL_TASK_RE.search(lower) else 'personal-admin'
        return {'kind':'task','reason':'scheduling','category':cat,'score':BADGE_MAP[cat]}
    if MEDICAL_TASK_RE.search(lower):
        return {'kind':'task','reason':'medical','category':'medical-admin','score':BADGE_MAP['medical-admin']}
    if ADMIN_TASK_RE.search(lower):
        return {'kind':'task','reason':'admin','category':'personal-admin','score':BADGE_MAP['personal-admin']}
    if HUMAN_ASK_RE.search(lower):
        return {'kind':'task','reason':'reply-needed','category':'personal-admin','score':0.82}
    return {'kind':'ignore','reason':'low-signal','category':'noise'}


def fetch_messages():
    if not (SID and TOKEN and PHONE):
        print('sms_scanner skipped missing_twilio_keys=1')
        return []
    params = {'To': PHONE, 'PageSize': 100, 'DateSent>=': (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()}
    url = BASE.format(sid=SID)
    msgs = []
    while url and len(msgs) < 300:
        r = requests.get(url, params=params if '?' not in url else None, auth=(SID, TOKEN), timeout=30)
        r.raise_for_status()
        data = r.json()
        for m in data.get('messages', []):
            if m.get('direction') == 'inbound': msgs.append(m)
        next_uri = data.get('next_page_uri')
        url = f'https://api.twilio.com{next_uri}' if next_uri else None
        params = None
    return msgs


def upsert_calendar(admin, guid, title, event_date, starts_at, location, base):
    row = admin.execute("SELECT id FROM calendar_items WHERE json_extract(source_details,'$.message_guid')=?", (guid,)).fetchone()
    payload = json.dumps(base)
    if row:
        admin.execute("UPDATE calendar_items SET title=?,event_date=?,starts_at=?,location=?,source_details=?,updated_at=datetime('now') WHERE id=?", (title, event_date, starts_at, location, payload, row['id']))
        return 0
    dup = admin.execute("SELECT id FROM calendar_items WHERE event_date=? AND starts_at LIKE '%' || ? AND LOWER(title)=LOWER(?) LIMIT 1", (event_date, starts_at, title)).fetchone()
    if dup:
        return 0
    admin.execute("INSERT INTO calendar_items (title,event_date,starts_at,location,source_details) VALUES (?,?,?,?,?)", (title, event_date, starts_at, location, payload))
    return 1


def main():
    admin = sqlite3.connect(ADMIN_DB)
    admin.row_factory = sqlite3.Row
    admin.execute('PRAGMA journal_mode=WAL')
    admin.execute('PRAGMA busy_timeout=30000')
    ensure_schema(admin)
    stats = {'tasks':0,'candidates':0,'calendar':0,'ignored':0,'skipped':0}
    for m in fetch_messages():
        sid = m['sid']
        text = clean_text(m.get('body') or '')
        if not text:
            stats['skipped'] += 1
            continue
        when = parsedate_to_datetime(m['date_sent']).astimezone() if m.get('date_sent') else datetime.now().astimezone()
        local_time = when.strftime('%Y-%m-%d %H:%M:%S')
        from_num = m.get('from') or ''
        base = {'contact': from_num, 'chat_identifier': from_num, 'message_date': local_time, 'capture_mode': 'sms', 'message_guid': sid, 'twilio_sid': sid}
        if PREFIX_RE.match(text):
            exists = admin.execute("SELECT 1 FROM tasks WHERE source='sms_in' AND json_extract(source_details,'$.message_guid')=?", (sid,)).fetchone()
            if exists:
                stats['skipped'] += 1
                continue
            due = parse_due_date(text, when)
            base.update({'classification':'text-in','reason':'sms-capture','due_date':due,'from_number':from_num})
            admin.execute("INSERT INTO tasks (title,description,due_date,priority,status,source,source_details) VALUES (?,?,?,?, 'open', 'sms_in', ?)", (task_title(text), text[:500], due, priority_for(text, due, when), json.dumps(base)))
            stats['tasks'] += 1
            continue
        info = classify_message(text, when)
        base.update({'classification':info['kind'],'reason':info.get('reason'),'category':info.get('category'),'from_number':from_num})
        if info['kind'] == 'ignore':
            admin.execute("INSERT INTO message_candidates (message_guid,chat_identifier,contact,message_text,message_date,score,status,source_details) VALUES (?,?,?,?,?,?, 'ignored', ?) ON CONFLICT(message_guid) DO UPDATE SET status='ignored',updated_at=datetime('now')", (sid, from_num, from_num, text[:1000], local_time, 0, json.dumps(base)))
            stats['ignored'] += 1
            continue
        if info['kind'] == 'calendar':
            base.update(info)
            stats['calendar'] += upsert_calendar(admin, sid, info['title'], info['event_date'], info['starts_at'], info.get('location'), base)
            admin.execute("INSERT INTO message_candidates (message_guid,chat_identifier,contact,message_text,message_date,score,status,source_details) VALUES (?,?,?,?,?,?, 'converted', ?) ON CONFLICT(message_guid) DO UPDATE SET status='converted',source_details=excluded.source_details,updated_at=datetime('now')", (sid, from_num, from_num, text[:1000], local_time, 1, json.dumps(base)))
            continue
        due = parse_due_date(text, when)
        base.update({'due_date': due, 'score': info['score']})
        admin.execute("INSERT INTO message_candidates (message_guid,chat_identifier,contact,message_text,message_date,score,status,source_details) VALUES (?,?,?,?,?,?, 'new', ?) ON CONFLICT(message_guid) DO UPDATE SET message_text=excluded.message_text,message_date=excluded.message_date,score=excluded.score,status=CASE WHEN message_candidates.status IN ('promoted','ignored','converted') THEN message_candidates.status ELSE 'new' END,source_details=excluded.source_details,updated_at=datetime('now')", (sid, from_num, from_num, text[:1000], local_time, info['score'], json.dumps(base)))
        stats['candidates'] += 1
    admin.commit(); admin.close()
    print(f"sms_scanner tasks={stats['tasks']} candidates={stats['candidates']} calendar={stats['calendar']} ignored={stats['ignored']} skipped={stats['skipped']}")

if __name__ == '__main__':
    main()
