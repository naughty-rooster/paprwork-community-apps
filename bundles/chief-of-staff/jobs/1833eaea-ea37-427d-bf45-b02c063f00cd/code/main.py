import json, os, re, sqlite3
from datetime import datetime, timedelta

ADMIN_DB = "/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db"
MSG_DB = os.path.expanduser("~/Library/Messages/chat.db")
PREFIX_RE = re.compile(r'^\s*(task|todo|reminder|add task)\b\s*[:\-]?\s*', re.I)
CAL_PREFIX_RE = re.compile(r'^\s*(calendar event|calendar|event)\b\s*[:\-]?\s*', re.I)
IGNORE_RE = re.compile(r'^(liked|loved|laughed at|emphasized|questioned|disliked)\s+["“]', re.I)
URL_ONLY_RE = re.compile(r'^(https?://\S+|\w+https?://\S+)$', re.I)
SHORT_ACK = {"ok","okay","k","thanks","thank you","sounds good","yes","no","done","got it","perfect","great"}
DAY_MAP = {"monday":0,"mon":0,"tuesday":1,"tue":1,"tues":1,"wednesday":2,"wed":2,"thursday":3,"thu":3,"thurs":3,"friday":4,"fri":4,"saturday":5,"sat":5,"sunday":6,"sun":6}
BAD_PARTS = {'streamtyped','NSMutableAttributedString','NSAttributedString','NSObject','NSMutableString','NSString','NSDictionary','NSNumber','NSValue','NSData','NSKeyedArchiver','__kIMMessagePartAttributeName'}
OTP_RE = re.compile(r'(verification code|security code|one[- ]time|passcode|we will never ask for this code|never ask for this code|2fa|auth code)', re.I)
MARKETING_RE = re.compile(r'(sign up to get notified|sale|dropping \d|promo|offer ends|reward points|unsubscribe|reply stop|attn.tv|travelocity|terms and conditions|privacy policy|newsletter|blogs?)', re.I)
RECEIPT_RE = re.compile(r'(view your receipt|track your delivery|order .*leaving|driver may make a stop|order has shipped|pick up the order)', re.I)
AUTO_IGNORE_RE = re.compile(r'(autopay is scheduled|bill .* is ready.*payment method on file|do not reply|for safety, you cannot be driving|reply yes to confirm|press a numeric key|important survey message|please disregard this message)', re.I)
FINANCE_ALERT_RE = re.compile(r'(transaction with|automatic minimum payment|payment is scheduled|min due:|stmnt bal|statement balance|account ending in|successfully validated your device|signed in\.|use the app to manage your devices|fraud alert|purchase was made|card ending|chase sapphire|zelle|venmo cashout|withdrawal of \$|deposit of \$|available credit|credit limit|payment received)', re.I)
SYSTEM_ALERT_RE = re.compile(r'(security alert|verification attempt|login attempt|device and signed in|manage your devices|otp|passcode)', re.I)
DELIVERY_ALERT_RE = re.compile(r'(delivery window|arriving today|arriving by|expected delivery|package .*delivered|shipment delayed|out for delivery|delivered at|left at the front door|stops away|driver is approaching)', re.I)
CARRIER_ALERT_RE = re.compile(r'(xfinity|comcast|service restoration|technician arrival|arrival window|service appointment|outage update|carrier alert|service interruption)', re.I)
ACCOUNT_STATUS_RE = re.compile(r'(transaction alert|statement is ready|statement available|payment confirmation|payment received|autopay|balance alert|low balance|overdraft|purchase alert|account alert|device sign-in|login code|parking session|parkmobile)', re.I)
NEVER_CALENDARIZE_RE = re.compile(r'(transaction with|payment alert|purchase alert|statement available|statement is ready|balance alert|low balance|overdraft|payment confirmation|payment received|service restoration window|technician arrival|arrival window|out for delivery|delivered at|left at the front door|stops away|shipment delayed|expected delivery|package .*delivered|device sign-in|security alert|verification code|otp|passcode|parking session|parkmobile|travelocity|free travelocity app)', re.I)
SCHEDULE_REQ_RE = re.compile(r'(time to schedule|upcoming availability|help you get .* on the schedule|schedule your follow up|schedule .* appointment|book .* appointment)', re.I)
APPT_RE = re.compile(r'(appointment|appt\b|upcoming virtual appointment|starts at|scheduled for|see you on|see you around|see you at|made an appt)', re.I)
DATE_SIGNAL_RE = re.compile(r'((?:on\s+)?(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\b.*?(?:\d{1,2}[:.,]\d{2}|\d{1,2}\s*[ap]m)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}.*?\d{1,2}[:.,]\d{2}|tomorrow.*?\d{1,2}[:.,]\d{2})', re.I)
CALENDAR_HINT_RE = re.compile(r'(confirm(ed)? your appointment|your appointment is confirmed|appointment reminder|virtual appointment|scheduled for .*\d{1,2}:\d{2}\s*[ap]m|made an appt)', re.I)
HUMAN_ASK_RE = re.compile(r'(can you|could you|will you|please|wanted to confirm|wanted to schedule|confirm that|do you want|are you available)', re.I)
ADMIN_TASK_RE = re.compile(r'(available to pay|invoice|statement|balance due|past due|pay online|payment|paperwork|claim|form|complete .*survey|send .*documents?|extension filed|efile|tax|child support|green card|citizenship)', re.I)
MEDICAL_TASK_RE = re.compile(r'(rx|prescription|pharmacy|ready for pick up|ready for pickup|pick up rx|therapy|dentist|neurologist|provider|clinic|medical|premera)', re.I)
FAMILY_LOGISTICS_RE = re.compile(r'(grab .* from|grab me|pick up .* for dinner|chopsticks|met market|grocery|groceries|dinner|lunch|breakfast|snack|drop off|pickup line|school pickup|soccer practice|camp pickup)', re.I)
RETAIL_IGNORE_RE = re.compile(r'(photo: good news|your order is ready for pickup|order ready for pickup)', re.I)
LOW_SIGNAL_RE = re.compile(r'(thinking of you|just wanted to check in|hope you are|love you|good morning|good night)', re.I)
LOCATION_RE = re.compile(r'(?:location:?|address:?)([^\n\.]+)', re.I)
PATIENT_RE = re.compile(r'\b(?:hi|hello)\s+([A-Z][a-z]+)\b|([A-Z][a-z]+)\'s appointment', re.I)
CLINICIAN_RE = re.compile(r'\b(?:with|provider:?|doctor:?|dr\.?|therapist:?|counselor:?|counsellor:?|with clinician:? )\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b')
DURATION_RE = re.compile(r'\b(\d{2,3})\s*(?:min|minutes?)\b', re.I)
VIDEO_RE = re.compile(r'(zoom|virtual|telehealth|video visit|google meet|teams)', re.I)
CALENDAR_LINK_RE = re.compile(r'(add to your calendar|calendar[: ]|confirm, cancel|click .*confirm|reply yes to confirm)', re.I)
GENERIC_PROVIDER_RE = re.compile(r'(appointment|assistance|text us|do not reply|reply stop|confirm|cancel|unsubscribe|virtual|upcoming|this number|2-day shipping|anyone|travelocity app|free travelocity app)', re.I)
PHONEISH_RE = re.compile(r'^[+()\-\d\s]{7,}$')


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


def next_weekday(today, day_num, force_next=False):
    days_ahead = (day_num - today.weekday()) % 7
    if force_next or days_ahead == 0:
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
        if d.weekday() < 5:  # Monday=0 ... Friday=4
            count += 1
    return d


def parse_due_date(text):
    if not text:
        return None
    lower, today = text.lower(), datetime.now().date()
    if any(x in lower for x in ["today", "tonight", "this evening"]):
        return today.isoformat()
    if "tomorrow" in lower:
        return (today + timedelta(days=1)).isoformat()
    m = re.search(r'\b(?:(next)\s+)?(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thurs|friday|fri|saturday|sat|sunday|sun)\b', lower)
    if m:
        return next_weekday(today, DAY_MAP[m.group(2)], m.group(1) == "next").isoformat()
    m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', lower)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else today.year
    if year < 100:
        year += 2000
    try:
        d = datetime(year, month, day).date()
        if not m.group(3) and d < today:
            d = datetime(today.year + 1, month, day).date()
        return d.isoformat()
    except ValueError:
        return None


def extract_body(blob):
    if not blob:
        return ''
    try:
        s = blob.decode('utf-8', 'ignore') if isinstance(blob, (bytes, bytearray)) else str(blob)
        parts = [p.strip(" +\n\t\r\x00") for p in re.findall(r'[ -~]{8,}', s)]
        parts = [p for p in parts if p not in BAD_PARTS and '__kIM' not in p and not p.startswith(('bplist00', '$', '['))]
        return max(parts, key=len)[:2000] if parts else ''
    except Exception:
        return ''


def clean_text(text):
    t = (text or '').replace('\uFFFC', ' ')
    t = re.sub(r'(^|\s)[a-zA-Z](?=https?://)', ' ', t)
    t = re.sub(r'(^|\s)[a-zA-Z](?=[A-Z][a-z])', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip(' :\n\t\r')
    return t


def task_title(text):
    cleaned = clean_text(PREFIX_RE.sub('', text or ''))
    lower = cleaned.lower()
    who = ''
    m = re.search(r"\b(?:from|with|at) ([A-Z][A-Za-z&'\-.]+(?: [A-Z][A-Za-z&'\-.]+){0,4})", cleaned)
    if m:
        who = re.sub(r'\b(message|statement|appointment)\b.*$', '', m.group(1), flags=re.I).strip(' ,')
    store = ''
    m2 = re.search(r'[:\-]\s*([A-Z][A-Z&\-.]{1,20})\b', cleaned)
    if m2:
        store = m2.group(1).strip(' ,')
    cleaned = re.sub(r'\b(today|tonight|tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,-')
    if re.search(r'(ready for pick\s*up|ready for pickup)', lower) and re.search(r'(rx|prescription|pharmacy|refill)', lower):
        target = store or who
        return (f'Errand: Pick up prescription from {target}' if target else 'Errand: Pick up prescription')[:120]
    if re.search(r'(statement .*available|available to pay|pay online|balance due|invoice)', lower):
        return (f'Make a payment: {who}' if who else 'Make a payment')[:120]
    if re.search(r'(past due|overdue|bill is due)', lower):
        return (f'Pay bill: {who}' if who else 'Pay bill')[:120]
    if re.search(r'(confirm|let me know|can you|could you|please respond|reply)', lower):
        return (f'Reply: {who}' if who else 'Reply')[:120]
    if re.search(r'(schedule|book|reschedule)', lower):
        return (f'Schedule: {who}' if who else 'Schedule')[:120]
    return (cleaned or 'Task from Messages')[:120]


def priority_for(text, due_date=None):
    lower = (text or '').lower()
    if any(x in lower for x in ["urgent", "asap", "immediately"]) or lower.count('!') >= 2:
        return 1
    if due_date == datetime.now().date().isoformat():
        return 1
    if any(x in lower for x in ["tomorrow", "this week", "soon", "important", "balance due", "past due"]):
        return 2
    return 3


def strip_ordinals(s):
    return re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', s)


def parse_appt_datetime(text, fallback_year, base_dt=None):
    cleaned = strip_ordinals(text.replace('(PT)', '').replace(' at ', ' '))
    cleaned = re.sub(r'(\d),(\d{2}\s*[APMapm]{2})', r'\1:\2', cleaned)
    cleaned = re.sub(r'\b(\d{1,2})(\d{2})\s*([APMapm]{2})\b', r'\1:\2 \3', cleaned)
    cleaned = re.sub(r'(\d{1,2}[:.,]\d{2})\s*[-–]\s*\d{1,2}[:.,]?\d{0,2}\s*([APMapm]{2})', r'\1 \2', cleaned)
    patterns = [
        r'(?:on\s+)?((?:[A-Za-z]+,?\s+)?[A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?),?\s+(\d{1,2}[:.,]\d{2}\s*[APMapm]{2})',
        r'(?:on\s+)?((?:[A-Za-z]+,?\s+)?[A-Za-z]+\s+[A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?),?\s+(\d{1,2}[:.,]\d{2}\s*[APMapm]{2})',
        r'(?:on\s+)?((?:[A-Za-z]+,?\s+)?[A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)\s+starts\s+at\s+(\d{1,2}[:.,]\d{2}\s*[APMapm]{2})',
        r'(?:on\s+)?((?:[A-Za-z]+,?\s+)?[A-Za-z]+\s+[A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)\s+starts\s+at\s+(\d{1,2}[:.,]\d{2}\s*[APMapm]{2})',
    ]
    for pat in patterns:
        match = re.search(pat, cleaned)
        if not match:
            continue
        ds, ts = match.group(1), match.group(2).upper().replace(' ', '').replace(',', ':')
        for fmt in ('%A, %B %d, %Y %I:%M%p', '%A, %b %d, %Y %I:%M%p', '%A, %B %d %Y %I:%M%p', '%A, %b %d %Y %I:%M%p', '%A %B %d, %Y %I:%M%p', '%A %b %d, %Y %I:%M%p', '%A %B %d %Y %I:%M%p', '%A %b %d %Y %I:%M%p', '%A, %B %d %I:%M%p', '%A, %b %d %I:%M%p', '%A %B %d %I:%M%p', '%A %b %d %I:%M%p', '%a, %B %d, %Y %I:%M%p', '%a, %b %d, %Y %I:%M%p', '%a, %B %d %Y %I:%M%p', '%a, %b %d %Y %I:%M%p', '%a %B %d, %Y %I:%M%p', '%a %b %d, %Y %I:%M%p', '%a %B %d %Y %I:%M%p', '%a %b %d %Y %I:%M%p', '%a, %B %d %I:%M%p', '%a, %b %d %I:%M%p', '%a %B %d %I:%M%p', '%a %b %d %I:%M%p', '%B %d, %Y %I:%M%p', '%b %d, %Y %I:%M%p', '%B %d %Y %I:%M%p', '%b %d %Y %I:%M%p', '%B %d %I:%M%p', '%b %d %I:%M%p'):
            try:
                dt = datetime.strptime(f'{ds} {ts}', fmt)
                if '%Y' not in fmt:
                    dt = dt.replace(year=fallback_year)
                return dt.date().isoformat(), dt.strftime('%-I:%M %p')
            except ValueError:
                pass
    base = base_dt or datetime.now()
    m = re.search(r'(?<!\d)(?:on\s+)?(?:the\s+)?(?!20\d{2}\b)(\d{1,2})(?:st|nd|rd|th)?(?:\s+around|\s+at)?\s+(\d{1,2}(?::|,)?\d{0,2})\s*([APMapm]{2})', cleaned, re.I)
    if m:
        day, time_raw, ap = int(m.group(1)), m.group(2).replace(',', ':'), m.group(3).upper()
        if ':' not in time_raw:
            time_raw += ':00'
        month, year = base.month, fallback_year
        if day < base.day - 2:
            month = 1 if month == 12 else month + 1
            year += 1 if month == 1 else 0
        try:
            dt = datetime.strptime(f'{year}-{month:02d}-{day:02d} {time_raw} {ap}', '%Y-%m-%d %I:%M %p')
            return dt.date().isoformat(), dt.strftime('%-I:%M %p')
        except ValueError:
            return None, None
    m = re.search(r'tomorrow(?:\s+around|\s+at)?\s+(\d{1,2}(?::|,)?\d{0,2})\s*([APMapm]{2})', cleaned, re.I)
    if m:
        time_raw, ap = m.group(1).replace(',', ':'), m.group(2).upper()
        if ':' not in time_raw:
            time_raw += ':00'
        dt = datetime.strptime(f"{base.strftime('%Y-%m-%d')} {time_raw} {ap}", '%Y-%m-%d %I:%M %p') + timedelta(days=1)
        return dt.date().isoformat(), dt.strftime('%-I:%M %p')
    return None, None


def tidy_name(raw):
    name = re.split(r'(?:\.\s| Do Not Reply| For assistance| Don\'t want| Reply STOP| to confirm)', raw)[0].strip(' ,')
    for stop in [' on ', ' at ', ' starts at ', ' scheduled for ']:
        if stop in name.lower():
            name = re.split(stop, name, flags=re.I)[0].strip(' ,')
    return name if 0 < len(name.split()) <= 5 and not re.search(r'\d{1,2}:\d{2}', name) else ''


def extract_patient(text):
    m = PATIENT_RE.search(text)
    if not m:
        return ''
    patient = tidy_name(next((g for g in m.groups() if g), ''))
    return patient.split()[0] if patient else ''


def extract_provider(text):
    candidates = []
    patterns = [
        (r'appointment with\s+(.+?)\s+on\s+[A-Z][a-z]+', 4),
        (r'this is\s+[^\.]+?\s+at\s+(.+?)\s+with a reminder for your appointment', 4),
        (r'this is\s+[^\.]+?\s+from\s+(.+?)\s+with a reminder for your appointment', 4),
        (r'reminder for [^\.]+? appointment [^\.]*? with\s+([^\.]+)', 3),
        (r'appointment with\s+([^\.]+)', 3),
        (r'with\s+([^\.]+)', 1),
        (r'from\s+([^\.]+)', 1),
    ]
    for pat, bonus in patterns:
        for raw in re.findall(pat, text, re.I):
            chunk = re.split(r'(?:\.\s| Click | Add to your calendar| Do Not Reply| Reply STOP| to confirm| on [A-Z][a-z]+,? [A-Z][a-z]+ \d{1,2}| on [A-Z][a-z]+ \d{1,2}| at \d{1,2}:\d{2}\s*[APMapm]{2}| with [A-Z][a-z]+(?: [A-Z][a-z]+){1,3}$)', raw)[0]
            name = tidy_name(chunk)
            if not name or GENERIC_PROVIDER_RE.search(name) or PHONEISH_RE.match(name):
                continue
            score = len(name.split()) + bonus
            if re.search(r'\b(LLC|PLLC|MD|DDS|PhD|Therapy|Clinic|Center|Health|Medical|Lab|StretchLab)\b', name):
                score += 2
            if re.search(r'^[A-Z][A-Za-z&]+(?: [A-Z][A-Za-z&]+){0,4}$', name):
                score += 1
            candidates.append((score, name))
    if not candidates:
        return ''
    return sorted(candidates, key=lambda x: (-x[0], len(x[1])))[0][1]


def extract_clinician(text, provider=''):
    chunks = re.findall(r'at \d{1,2}:\d{2}\s*[APMapm]{2}\s+with\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})', text)
    chunks += re.findall(r'on [A-Z][a-z]+,? [A-Z][a-z]+ \d{1,2},? \d{4}? \d{1,2}:\d{2}\s*[APMapm]{2}\s+with\s+([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})', text)
    chunks += CLINICIAN_RE.findall(text)
    for raw in chunks:
        name = tidy_name(raw)
        if not name or name == provider or (provider and name.replace('-', ' ') in provider.replace('-', ' ')) or GENERIC_PROVIDER_RE.search(name):
            continue
        if len(name.split()) >= 2:
            return name
    return ''


def extract_location(text):
    if VIDEO_RE.search(text):
        return 'Virtual'
    m = LOCATION_RE.search(text)
    if not m:
        return ''
    loc = re.split(r'(?:\.\s| Reply STOP| to confirm| with )', m.group(1))[0].strip(' ,')
    if re.search(r'\d{1,2}:\d{2}', loc):
        return ''
    return loc[:120]


def appointment_mode(text, location=''):
    lower = text.lower()
    if location == 'Virtual' or VIDEO_RE.search(text):
        return 'virtual'
    if any(x in lower for x in ['in person', 'in-person', 'office visit', 'clinic visit']):
        return 'in-person'
    return ''


def extract_topic(text):
    lower = text.lower()
    simple = [r'(swimming)', r'(pressure washing)', r'(power washing)', r'(gutter cleaning)', r'(house cleaning)', r'(window cleaning)', r'(yard work)', r'(roof repair)', r'(estimate)', r'(inspection)']
    for pat in simple:
        m = re.search(pat, lower)
        if m:
            return m.group(1)
    stay = re.search(r'confirming your stay at\s+(.+?)\s+from\s+[A-Z][a-z]{2}', text, re.I)
    if stay:
        return f'Stay at {tidy_name(stay.group(1))}'
    if 'xfinity' in lower and ('service interruption' in lower or 'working to resolve' in lower):
        return 'Xfinity service restoration window'
    if 'delivery date' in lower or '2-day shipping' in lower:
        return 'Delivery window'
    return ''


def build_calendar_title(patient='', mode='', provider='', clinician='', contact='', topic=''):
    who = provider or clinician or (contact if contact and not PHONEISH_RE.match((contact or '').strip()) else '')
    if topic and who and not re.search(r'^(stay at|delivery window|xfinity service restoration window)', topic, re.I):
        label = f'{topic} with {who}'
    elif topic:
        label = topic
    else:
        label = f'{mode} appointment' if mode else 'appointment'
        label = f'{label} with {who}' if who else label
    pretty = label[:1].upper() + label[1:]
    return f'{patient}: {pretty}' if patient and not topic else pretty


def explicit_calendar_details(text, local_time, contact='', context=''):
    body = clean_text(CAL_PREFIX_RE.sub('', text or ''))
    base_dt = datetime.fromisoformat(local_time.replace(' ', 'T')) if local_time else datetime.now()
    year = base_dt.year
    event_date, starts_at = parse_appt_datetime(body, year, base_dt)
    if not (event_date and starts_at):
        return None
    title = re.split(r',?\s*(?:on\s+)?(?:today|tomorrow|mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|\d{1,2}/\d{1,2}/\d{2,4})\b', body, maxsplit=1, flags=re.I)[0].strip(' ,-')
    topic = extract_topic(body)
    if not title:
        title = topic or 'Calendar event'
    meta = {
        'kind': 'calendar', 'category': 'calendar', 'reason': 'explicit-calendar', 'title': title[:120],
        'event_date': event_date, 'starts_at': starts_at, 'patient': '', 'provider': '', 'clinician': '',
        'mode': '', 'location': extract_location(body), 'topic': topic, 'duration_minutes': duration_minutes(body),
        'notes': body[:500], 'context_excerpt': clean_text(' '.join(x for x in [context, text] if x))[:500],
        'calendar_confidence': 0.99, 'provider_confidence': 0.0, 'contact_confidence': 0.35 if contact and not PHONEISH_RE.match((contact or '').strip()) else 0.0
    }
    return meta


def duration_minutes(text):
    m = DURATION_RE.search(text)
    if m:
        return max(15, min(180, int(m.group(1))))
    lower = text.lower()
    if any(x in lower for x in ['therapy', 'counseling', 'counselling']):
        return 50
    return 60


def reminder_date_mismatch(event_date, reference_dt, text=''):
    if not event_date or not reference_dt:
        return False
    lower = (text or '').lower()
    reminder_like = any(token in lower for token in ['reminder for', 'appointment reminder', 'starts at', "don't want these? reply stop", 'reply stop', 'confirmed under'])
    if not reminder_like:
        return False
    try:
        delta = (datetime.fromisoformat(event_date).date() - reference_dt.date()).days
    except ValueError:
        return False
    return abs(delta) > 7


def appointment_details(text, local_time, contact, context=''):
    cleaned = clean_text(text)
    merged = clean_text(' '.join(x for x in [context, text] if x))
    base_dt = datetime.fromisoformat(local_time.replace(' ', 'T')) if local_time else datetime.now()
    year = base_dt.year
    event_date, starts_at = parse_appt_datetime(cleaned, year, base_dt)
    if not (event_date and starts_at):
        event_date, starts_at = parse_appt_datetime(merged, year, base_dt)
    if event_date and reminder_date_mismatch(event_date, base_dt, merged):
        return None
    patient = extract_patient(cleaned) or extract_patient(merged)
    provider = extract_provider(cleaned) or extract_provider(merged)
    clinician = extract_clinician(cleaned, provider) or extract_clinician(merged, provider)
    location = extract_location(cleaned) or extract_location(merged)
    mode = appointment_mode(merged, location)
    topic = extract_topic(merged)
    provider_conf = 0.65 if provider else 0.0
    contact_conf = 0.35 if contact and not PHONEISH_RE.match((contact or '').strip()) else 0.0
    confidence = 0.0
    if event_date and starts_at:
        confidence += 0.68
    if provider_conf:
        confidence += 0.2
    elif topic:
        confidence += 0.14
    elif contact_conf:
        confidence += 0.08
    if location:
        confidence += 0.05
    if CALENDAR_LINK_RE.search(merged.lower()):
        confidence += 0.08
    if any(x in merged.lower() for x in ['see you on', 'see you around', 'scheduled for', 'appointment reminder', 'upcoming virtual appointment', 'confirmed']):
        confidence += 0.08
    confidence = round(min(confidence, 0.99), 2)
    title = build_calendar_title(patient, mode, provider, clinician, contact, topic)
    payload = {'reason': 'appointment', 'title': title, 'event_date': event_date, 'starts_at': starts_at, 'patient': patient, 'provider': provider, 'clinician': clinician, 'mode': mode, 'location': location, 'topic': topic, 'duration_minutes': duration_minutes(merged), 'notes': cleaned[:500], 'context_excerpt': merged[:500], 'calendar_confidence': confidence, 'provider_confidence': provider_conf, 'contact_confidence': contact_conf}
    if event_date and starts_at and confidence >= 0.68:
        payload.update({'kind': 'calendar', 'category': 'calendar'})
        return payload
    payload.update({'kind': 'task', 'category': 'calendar-review', 'reason': 'appointment-review', 'score': max(0.82, confidence or 0.82)})
    return payload


def classify_message(text, local_time, contact, context=''):
    lower = clean_text(text).lower()
    if not lower or lower in SHORT_ACK or IGNORE_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'ack', 'category': 'noise'}
    if URL_ONLY_RE.match(lower) or (len(lower) < 14 and ' ' not in lower):
        return {'kind': 'ignore', 'reason': 'fragment', 'category': 'noise'}
    if OTP_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'otp', 'category': 'noise'}
    if FINANCE_ALERT_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'finance-alert', 'category': 'noise'}
    if SYSTEM_ALERT_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'system', 'category': 'noise'}
    if DELIVERY_ALERT_RE.search(lower) or CARRIER_ALERT_RE.search(lower) or ACCOUNT_STATUS_RE.search(lower) or NEVER_CALENDARIZE_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'non-action-alert', 'category': 'noise'}
    if RETAIL_IGNORE_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'retail', 'category': 'noise'}
    if RECEIPT_RE.search(lower) and 'rx' not in lower and 'prescription' not in lower:
        return {'kind': 'ignore', 'reason': 'receipt', 'category': 'noise'}
    if (APPT_RE.search(lower) or CALENDAR_HINT_RE.search(lower) or DATE_SIGNAL_RE.search(lower)) and not SCHEDULE_REQ_RE.search(lower):
        info = appointment_details(text, local_time, contact, context)
        if info:
            if info.get('event_date'):
                try:
                    if datetime.fromisoformat(info['event_date']).date() < (datetime.now().date() - timedelta(days=1)):
                        return {'kind': 'ignore', 'reason': 'past-appointment', 'category': 'noise'}
                except ValueError:
                    pass
            return info
    if MARKETING_RE.search(lower):
        return {'kind': 'ignore', 'reason': 'marketing', 'category': 'noise'}
    if AUTO_IGNORE_RE.search(lower) and 'appointment' not in lower:
        return {'kind': 'ignore', 'reason': 'system', 'category': 'noise'}
    if LOW_SIGNAL_RE.search(lower) and '?' not in lower:
        return {'kind': 'ignore', 'reason': 'social', 'category': 'noise'}
    if FAMILY_LOGISTICS_RE.search(lower):
        return {'kind': 'task', 'reason': 'family-logistics', 'category': 'family-logistics', 'score': 0.58}
    if SCHEDULE_REQ_RE.search(lower):
        category = 'medical-admin' if MEDICAL_TASK_RE.search(lower) else 'personal-admin'
        score = 0.92 if category == 'medical-admin' else 0.84
        return {'kind': 'task', 'reason': 'scheduling', 'category': category, 'score': score}
    if MEDICAL_TASK_RE.search(lower):
        return {'kind': 'task', 'reason': 'medical', 'category': 'medical-admin', 'score': 0.96}
    if ADMIN_TASK_RE.search(lower):
        return {'kind': 'task', 'reason': 'admin', 'category': 'personal-admin', 'score': 0.93}
    if HUMAN_ASK_RE.search(lower):
        return {'kind': 'task', 'reason': 'reply', 'category': 'personal-admin', 'score': 0.88}
    return {'kind': 'ignore', 'reason': 'low-signal', 'category': 'noise'}


def msg_rows(conn):
    q = """
    SELECT m.guid, m.ROWID AS message_rowid, COALESCE(c.chat_identifier, h.id, '') AS chat_identifier,
           COALESCE(h.id, c.display_name, c.chat_identifier, '') AS contact,
           m.text, m.subject, m.attributedBody,
           datetime((m.date/1000000000)+978307200,'unixepoch','localtime') AS local_time,
           m.is_from_me
    FROM message m
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN chat c ON c.ROWID = cmj.chat_id
    WHERE datetime((m.date/1000000000)+978307200,'unixepoch','localtime') >= datetime('now','-180 days','localtime')
    ORDER BY m.date DESC LIMIT 2500
    """
    return conn.execute(q).fetchall()


def msg_rows(conn):
    q = """
    SELECT m.guid, m.ROWID AS message_rowid, COALESCE(c.chat_identifier, h.id, '') AS chat_identifier,
           COALESCE(h.id, c.display_name, c.chat_identifier, '') AS contact,
           m.text, m.subject, m.attributedBody,
           datetime((m.date/1000000000)+978307200,'unixepoch','localtime') AS local_time,
           m.is_from_me
    FROM message m
    LEFT JOIN handle h ON h.ROWID = m.handle_id
    LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN chat c ON c.ROWID = cmj.chat_id
    WHERE datetime((m.date/1000000000)+978307200,'unixepoch','localtime') >= datetime('now','-180 days','localtime')
    ORDER BY m.date DESC LIMIT 2500
    """
    return conn.execute(q).fetchall()


def remove_task_for_guid(admin, guid):
    admin.execute("DELETE FROM tasks WHERE source IN ('messages','text_in') AND json_extract(source_details,'$.message_guid')=?", (guid,))




def should_delete_calendar_item(title, meta, text=''):
    title_lower = (title or '').strip().lower()
    combined = ' '.join(x for x in [text, meta.get('description',''), meta.get('notes',''), meta.get('context_excerpt',''), meta.get('thread_preview',''), meta.get('summary','')] if x).lower()
    message_date = (meta.get('message_date') or '').strip()
    app_created = meta.get('app_created') or meta.get('google_created') or 'created by personal admin assistant' in combined
    if not app_created and not meta.get('event_id'):
        return False
    if meta.get('source_task_id'):
        return True
    if message_date and meta.get('reason') == 'appointment':
        try:
            base_dt = datetime.fromisoformat(message_date.replace(' ', 'T'))
        except ValueError:
            base_dt = None
        if base_dt and reminder_date_mismatch(meta.get('event_date'), base_dt, combined):
            return True
    if FINANCE_ALERT_RE.search(combined) or SYSTEM_ALERT_RE.search(combined) or DELIVERY_ALERT_RE.search(combined) or CARRIER_ALERT_RE.search(combined) or ACCOUNT_STATUS_RE.search(combined) or NEVER_CALENDARIZE_RE.search(combined):
        return True
    if 'travelocity' in title_lower or 'travelocity' in combined or 'parkmobile' in title_lower or 'parkmobile' in combined:
        return True
    if title_lower in {'appointment with anyone', 'confirm appointment: no-reply@seattle.gov', 'respond to message: quicken'}:
        return True
    if re.match(r'^(schedule:|confirm appointment:|follow[- ]?up with:?|respond to message:)', title_lower) and re.search(r'(payment|receipt|transaction|verification code|otp|starts in approximately|appointment reminder|payment confirmation|order confirmation)', combined):
        return True
    if title_lower.startswith('appointment with ') and re.search(r'(transaction with|payment|purchase alert|made a \$|free travelocity app)', combined):
        return True
    return False


def mark_calendar_delete_pending(admin, row_id, meta, reason):
    meta.update({'delete_pending': 1, 'delete_reason': reason})
    admin.execute("UPDATE calendar_items SET source_details=?,updated_at=datetime('now') WHERE id=?", (json.dumps(meta), row_id))


def cleanup_existing_calendar(admin):
    rows = admin.execute("SELECT id,title,source_details FROM calendar_items WHERE source_details IS NOT NULL AND source_details<>''").fetchall()
    fixed = 0
    for row in rows:
        try:
            meta = json.loads(row['source_details'] or '{}')
        except Exception:
            continue
        text = ' '.join([row['title'] or '', meta.get('description',''), meta.get('notes',''), meta.get('context_excerpt',''), meta.get('thread_preview',''), meta.get('summary','')]).strip()
        if not text:
            continue
        if should_delete_calendar_item(row['title'], meta, text):
            if meta.get('event_id'):
                mark_calendar_delete_pending(admin, row['id'], meta, 'noise-cleanup')
            else:
                admin.execute("DELETE FROM calendar_items WHERE id=?", (row['id'],))
            fixed += 1
            continue
        lower_text = text.lower()
        if meta.get('capture_mode') == 'messages' and (FINANCE_ALERT_RE.search(lower_text) or SYSTEM_ALERT_RE.search(lower_text) or DELIVERY_ALERT_RE.search(lower_text) or CARRIER_ALERT_RE.search(lower_text) or ACCOUNT_STATUS_RE.search(lower_text) or NEVER_CALENDARIZE_RE.search(lower_text)):
            if meta.get('event_id'):
                mark_calendar_delete_pending(admin, row['id'], meta, 'message-noise')
            else:
                admin.execute("DELETE FROM calendar_items WHERE id=?", (row['id'],))
            fixed += 1
            continue
        provider = meta.get('provider') or extract_provider(text)
        clinician = meta.get('clinician') or extract_clinician(text, provider)
        patient = meta.get('patient') or extract_patient(text)
        topic = meta.get('topic') or extract_topic(text)
        mode = meta.get('mode') or appointment_mode(text, meta.get('location',''))
        better = build_calendar_title(patient, mode, provider, clinician, meta.get('contact',''), topic).strip()
        current = (row['title'] or '').strip()
        if not better or better == current:
            continue
        if ('appointment with' not in current.lower() and 'appointment ·' not in current.lower() and 'travelocity' not in current.lower() and 'xfinity' not in current.lower()):
            continue
        meta.update({'provider': provider, 'clinician': clinician, 'patient': patient, 'topic': topic, 'mode': mode, 'title': better})
        admin.execute("UPDATE calendar_items SET title=?,source_details=?,updated_at=datetime('now') WHERE id=?", (better[:120], json.dumps(meta), row['id']))
        fixed += 1
    return fixed

def upsert_calendar(admin, guid, title, event_date, starts_at, location, base):
    row = admin.execute("SELECT id FROM calendar_items WHERE json_extract(source_details,'$.message_guid')=?", (guid,)).fetchone()
    payload = json.dumps(base)
    if row:
        admin.execute("UPDATE calendar_items SET title=?,event_date=?,starts_at=?,location=?,source_details=?,updated_at=datetime('now') WHERE id=?", (title, event_date, starts_at, location, payload, row['id']))
        return 0
    dup = admin.execute("SELECT id FROM calendar_items WHERE event_date=? AND starts_at LIKE '%' || ? AND (LOWER(title)=LOWER(?) OR COALESCE(location,'')=COALESCE(?,location,'')) LIMIT 1", (event_date, starts_at, title, location or None)).fetchone()
    if dup:
        return 0
    admin.execute("INSERT INTO calendar_items (title,event_date,starts_at,location,source_details) VALUES (?,?,?,?,?)", (title, event_date, starts_at, location, payload))
    return 1


def set_candidate_status(admin, guid, status):
    admin.execute("UPDATE message_candidates SET status=?,updated_at=datetime('now') WHERE message_guid=? AND status='new'", (status, guid))


def cleanup_existing_message_tasks(admin):
    rows = admin.execute("SELECT id,title,description,source_details FROM tasks WHERE status='open' AND source IN ('messages','text_in')").fetchall()
    removed = 0
    for row in rows:
        try:
            meta = json.loads(row['source_details'] or '{}')
        except Exception:
            meta = {}
        if meta.get('capture_mode') != 'messages':
            continue
        text = ' '.join([row['title'] or '', row['description'] or '', meta.get('notes',''), meta.get('context_excerpt',''), meta.get('thread_preview','')]).strip().lower()
        if not text:
            continue
        if FINANCE_ALERT_RE.search(text) or SYSTEM_ALERT_RE.search(text) or DELIVERY_ALERT_RE.search(text) or CARRIER_ALERT_RE.search(text) or ACCOUNT_STATUS_RE.search(text) or NEVER_CALENDARIZE_RE.search(text):
            admin.execute("DELETE FROM tasks WHERE id=?", (row['id'],))
            removed += 1
    return removed


def close_noise_candidates(admin):
    admin.execute("""UPDATE message_candidates
                     SET status='ignored', updated_at=datetime('now')
                     WHERE status='new' AND (
                       score < 0.8
                       OR message_text REGEXP '(?i)(verification code|receipt|track your delivery|pick up the order|cannot be driving|photo: good news|order is ready for pickup|transaction with|payment alert|statement available|service restoration window|arrival window|out for delivery|shipment delayed|delivered at|stops away)'
                       OR json_extract(source_details,'$.category')='family-logistics'
                     )""")


def main():
    admin = sqlite3.connect(ADMIN_DB)
    admin.row_factory = sqlite3.Row
    admin.create_function('REGEXP', 2, lambda pat, val: 1 if val and re.search(pat, val) else 0)
    admin.execute('PRAGMA journal_mode=WAL')
    admin.execute('PRAGMA busy_timeout=30000')
    ensure_schema(admin)
    msgs = sqlite3.connect(f'file:{MSG_DB}?mode=ro', uri=True)
    msgs.row_factory = sqlite3.Row
    rows = msg_rows(msgs)
    prepared = []
    for row in rows:
        raw_text = row['text'] or row['subject'] or extract_body(row['attributedBody'])
        text = clean_text(raw_text)
        if text:
            prepared.append({'guid': row['guid'], 'message_rowid': row['message_rowid'], 'text': text, 'contact': row['contact'], 'chat_identifier': row['chat_identifier'], 'local_time': row['local_time'], 'is_from_me': int(row['is_from_me']) == 1})
    by_chat = {}
    for row in sorted(prepared, key=lambda r: (r['chat_identifier'] or '', r['local_time'] or '')):
        by_chat.setdefault(row['chat_identifier'] or row['guid'], []).append(row)
    stats = {'tasks': 0, 'candidates': 0, 'calendar': 0, 'ignored': 0, 'skipped': 0}
    for row in prepared:
        guid, text = row['guid'], row['text']
        if not text:
            stats['skipped'] += 1
            continue
        is_from_me = row['is_from_me']
        contact, chat_id, local_time = row['contact'], row['chat_identifier'], row['local_time']
        thread = by_chat.get(chat_id or guid, [])
        context = ' '.join(x['text'] for x in thread if x['guid'] != guid)[:800]
        base = {'contact': contact, 'chat_identifier': chat_id, 'message_date': local_time, 'capture_mode': 'messages', 'message_guid': guid, 'thread_preview': context[:300]}
        if is_from_me and CAL_PREFIX_RE.match(text):
            info = explicit_calendar_details(text, local_time, contact, context)
            if info:
                base.update({'classification': 'calendar', 'reason': info.get('reason'), 'category': info.get('category'), 'calendar_confidence': info.get('calendar_confidence'), 'provider_confidence': 0, 'contact_confidence': info.get('contact_confidence'), 'event_date': info['event_date'], 'starts_at': info['starts_at'], 'title': info['title'], 'location': info.get('location'), 'topic': info.get('topic'), 'duration_minutes': info.get('duration_minutes'), 'notes': info.get('notes'), 'context_excerpt': info.get('context_excerpt')})
                remove_task_for_guid(admin, guid)
                stats['calendar'] += upsert_calendar(admin, guid, info['title'], info['event_date'], info['starts_at'], info.get('location'), base)
                continue
        if is_from_me and PREFIX_RE.match(text):
            exists = admin.execute("SELECT 1 FROM tasks WHERE source='text_in' AND json_extract(source_details,'$.message_guid')=?", (guid,)).fetchone()
            if exists:
                stats['skipped'] += 1
                continue
            due_date = parse_due_date(text) or three_business_days().isoformat()
            base.update({'classification': 'text-in', 'reason': 'self-capture', 'due_date': due_date, 'due_date_defaulted': due_date == three_business_days().isoformat()})
            admin.execute("INSERT INTO tasks (title,description,due_date,priority,status,source,source_details) VALUES (?,?,?,?, 'open', 'text_in', ?)", (task_title(text), text[:500], due_date, priority_for(text, due_date), json.dumps(base)))
            stats['tasks'] += 1
            continue
        if is_from_me:
            stats['skipped'] += 1
            continue
        info = classify_message(text, local_time, contact, context)
        base.update({'classification': info['kind'], 'reason': info.get('reason'), 'category': info.get('category'), 'calendar_confidence': info.get('calendar_confidence'), 'provider_confidence': info.get('provider_confidence'), 'contact_confidence': info.get('contact_confidence')})
        if info['kind'] == 'ignore':
            set_candidate_status(admin, guid, 'ignored')
            stats['ignored'] += 1
            continue
        if info['kind'] == 'calendar':
            remove_task_for_guid(admin, guid)
            base.update({'event_date': info['event_date'], 'starts_at': info['starts_at'], 'title': info['title'], 'patient': info.get('patient'), 'provider': info.get('provider'), 'clinician': info.get('clinician'), 'mode': info.get('mode'), 'location': info.get('location'), 'topic': info.get('topic'), 'duration_minutes': info.get('duration_minutes'), 'notes': info.get('notes'), 'context_excerpt': info.get('context_excerpt')})
            stats['calendar'] += upsert_calendar(admin, guid, info['title'], info['event_date'], info['starts_at'], info.get('location'), base)
            set_candidate_status(admin, guid, 'converted')
            continue
        due_date = parse_due_date(text) or three_business_days().isoformat()
        base.update({'due_date': due_date, 'score': info['score']})
        admin.execute("""INSERT INTO message_candidates (message_guid,chat_identifier,contact,message_text,message_date,score,status,source_details)
                         VALUES (?,?,?,?,?,?, 'new', ?)
                         ON CONFLICT(message_guid) DO UPDATE SET
                           message_text=excluded.message_text,
                           message_date=excluded.message_date,
                           score=excluded.score,
                           status=CASE WHEN message_candidates.status IN ('promoted','ignored','converted') THEN message_candidates.status ELSE 'new' END,
                           source_details=excluded.source_details,
                           updated_at=datetime('now')""", (guid, chat_id, contact, text[:1000], local_time, info['score'], json.dumps(base)))
        stats['candidates'] += 1
    admin.execute("""DELETE FROM calendar_items
                     WHERE json_extract(source_details,'$.capture_mode')='messages'
                       AND EXISTS (
                         SELECT 1 FROM calendar_items c2
                         WHERE c2.id<>calendar_items.id
                           AND c2.event_date=calendar_items.event_date
                           AND c2.starts_at LIKE '%' || calendar_items.starts_at
                           AND json_extract(c2.source_details,'$.capture_mode') IS NULL)""")
    close_noise_candidates(admin)
    task_fixed = cleanup_existing_message_tasks(admin)
    calendar_fixed = cleanup_existing_calendar(admin)
    admin.commit()
    msgs.close(); admin.close()
    print(f"messages scanned={len(rows)} calendar_added={stats['calendar']} candidates_upserted={stats['candidates']} self_tasks_added={stats['tasks']} ignored={stats['ignored']} skipped={stats['skipped']} message_tasks_removed={task_fixed} calendar_titles_fixed={calendar_fixed}")


if __name__ == '__main__':
    main()
