import base64, email.utils, json, re, sqlite3, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone

OAUTH_DB = '/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB = '/Users/coreybadcock/Papr/jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
USER_EMAIL = 'cbadcock@gmail.com'
SIMILAR_LOOKBACK_DAYS = 7
MAX_RESULTS = 100
SKIP_SUBJECT_PATTERNS = [r'payment receipt', r'payment confirmation', r'order receipt', r'delivered:', r'shipped:', r'preparing to ship', r'subscription cancel', r'membership .*cancel', r'refund is confirmed', r'you signed in with a new device', r'security alert', r'one-time sign in link', r'mfa code', r'verification code', r'telehealth verification code', r'google play order receipt', r'at work edelivery notification', r'weekly financial alerts', r'credit file', r'activate your streaming subscriptions', r'large transaction notice', r'big deposit incoming', r'order confirmation', r'price changes:', r'who was the real pontius pilate', r'updates$', r'welcome digital marketing professionals', r'strategic briefing', r'guide to privacy and safety', r'teacher appreciation week', r'your fountain video visit is confirmed', r'your fountain video visit starts', r'invitation for telehealth appointment', r'automatic reply:', r'sounds good', r'see you then', r'new xfinity sign in', r'you.re now sharing data with quicken', r'your credit card payment is scheduled']
ACTION_KEYWORDS = ['past due', 'pay your bill', 'view and respond', 'new message via clio', 'verify your quicken account', 'please reply', 'can you', 'could you', 'need you to', 'please send', 'please review', 'please confirm', 'please complete', 'please upload', 'please sign', 'please submit', 'summer camp planning', 'check game times']
RESOLVED_PHRASES = ['confirmed', 'filed', 'extension filed', 'done', 'completed', 'taken care of', 'scheduled', 'sounds good', 'see you then', 'paid', 'submitted', 'thanks got it', 'we found the answer', "we weren't able to locate it", 'keep an eye out', 'will provide an update']
PROMO_SENDERS = ['amazon.com', 'primevideo.com', 'medium.com', 'skool.com', 'appsheet.com', 'nationalgeographic.com']

def api_get(token, url, params=None):
    if params:
        pairs=[]
        for k,v in params.items():
            if isinstance(v, list):
                for item in v: pairs.append((k,item))
            else:
                pairs.append((k,v))
        url = url + ('&' if '?' in url else '?') + urllib.parse.urlencode(pairs)
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def parse_headers(payload): return {h.get('name',''): h.get('value','') for h in payload.get('headers',[])}
def clean_text(text): return re.sub(r'\s+',' ', re.sub(r'https?://\S+|<[^>]+>', ' ', text or '')).strip()

def decode_part(part):
    out=[]; mime=(part.get('mimeType') or '').lower(); data=(part.get('body') or {}).get('data')
    if data and mime in ('text/plain','text/html',''):
        try: out.append(base64.urlsafe_b64decode(data + '===').decode('utf-8','ignore'))
        except: pass
    for p in part.get('parts') or []: out.extend(decode_part(p))
    return out

def get_message_text(msg):
    parts=decode_part(msg.get('payload') or {})
    txt=clean_text(' '.join(parts))
    return txt or clean_text(msg.get('snippet',''))

def is_user_sender(from_header): return USER_EMAIL in (from_header or '').lower()

def org_from_header(from_header):
    name, addr = email.utils.parseaddr(from_header or '')
    low=(from_header or '').lower()
    for key,val in [('outdoorsforall','Outdoors for All'),('weinrich','Weinrich Immigration Law'),('clio','Weinrich Immigration Law'),('seattle.gov','Seattle City Light'),('quicken','Quicken'),('seattleschools','Ingraham Unified'),('mindful','Mindful Therapy Group'),('demaarlaw','de Maar Law')]:
        if key in low: return val
    base=(name or addr.split('@')[0] or 'Unknown').strip('" <>()')
    return re.sub(r'\bvia .*','',base,flags=re.I).strip() or 'Unknown'

def normalize_title(subject, from_header, text):
    s=(subject or '').lower(); t=(text or '').lower(); org=org_from_header(from_header)
    if 'past due' in s or 'pay your bill' in t: return f'Make a payment: {org}'
    if 'new message' in s or ('view and respond' in t and 'clio' in t): return f'Respond to secure message: {org}'
    if 'verify your quicken account' in s: return 'Verify account: Quicken'
    if 'summer camp planning' in s: return 'Respond to message: Outdoors for All'
    if 'check game times' in s or 'game times' in s: return 'Review game schedule: Ingraham Unified'
    if 'new orders filed' in s: return f'Review legal filing: {org}'
    if any(k in t for k in ['please upload','attachment required']): return f'Upload document: {org}'
    if any(k in t for k in ['please submit','submit form']): return f'Submit form: {org}'
    if any(k in t for k in ['please send','send over','send information']): return f'Send information: {org}'
    if any(k in t for k in ['please reply','can you','could you','need you to','respond']): return f'Respond to message: {org}'
    return f'Follow up with: {org}'

def is_obvious_skip(subject, from_header, snippet):
    low=' '.join([subject or '', from_header or '', snippet or '']).lower()
    if any(dom in low for dom in PROMO_SENDERS): return True, 'promo_or_newsletter'
    for pat in SKIP_SUBJECT_PATTERNS:
        if re.search(pat, low): return True, 'non_actionable_notification'
    return False, None

def candidate_by_surface(subject, from_header, snippet):
    low=' '.join([subject or '', from_header or '', snippet or '']).lower()
    return any(k in low for k in ACTION_KEYWORDS)

def thread_resolved(thread_msgs):
    ordered=sorted(thread_msgs, key=lambda m: int(m.get('internalDate','0')))
    last=ordered[-1]; last_headers=parse_headers(last.get('payload') or {}); last_from=last_headers.get('From',''); last_text=get_message_text(last).lower()
    if is_user_sender(last_from): return True, 'later_user_reply'
    if any(p in last_text for p in RESOLVED_PHRASES): return True, 'later_resolved_language'
    return False, None

def evaluate_actionability(subject, from_header, text):
    low=' '.join([subject or '', from_header or '', text or '']).lower()
    if 'past due' in low and 'ignore this reminder if paid' in low: return True, 'payment_due'
    if 'new message via clio' in low or ('view and respond' in low and 'clio' in low): return True, 'secure_message'
    if 'summer camp planning' in low: return True, 'reply_requested'
    if 'verify your quicken account' in low: return True, 'verification_requested'
    if 'check game times' in low and 'make sure you know the schedule' in low: return True, 'review_schedule'
    if any(phrase in low for phrase in ['will send you an update','keep an eye out',"we weren't able to locate it",'sounds good','see you then']): return False, 'status_only'
    if 'review it before we chat' in low: return False, 'no_explicit_ask'
    if any(k in low for k in ['please reply','can you','could you','need you to','please review','please confirm','please complete','please upload','please send','please sign','please submit']): return True, 'explicit_ask'
    return False, 'no_explicit_ask'

def due_date_for(subject, text):
    low=' '.join([subject or '', text or '']).lower(); today=str(datetime.now(timezone.utc).date())
    if 'past due' in low: return today
    return None

def priority_for(subject, text):
    low=' '.join([subject or '', text or '']).lower()
    if 'past due' in low or 'overdrawn' in low: return 1
    if any(k in low for k in ['verify your quicken account','new message via clio','view and respond']): return 1
    return 2

def recent_open_similar(cur, from_header, title):
    row=cur.execute("SELECT id FROM tasks WHERE status='open' AND source='gmail' AND created_at >= datetime('now', ?) AND (json_extract(source_details,'$.from') = ? OR title = ?) LIMIT 1", (f'-{SIMILAR_LOOKBACK_DAYS} days', from_header, title)).fetchone()
    return row[0] if row else None

oauth=sqlite3.connect(OAUTH_DB)
admin=sqlite3.connect(ADMIN_DB, timeout=30)
admin.execute('PRAGMA journal_mode=WAL')
admin.execute('PRAGMA busy_timeout=30000')
token=oauth.execute("SELECT access_token FROM oauth_tokens WHERE connection_id='google:personal'").fetchone()[0]
query='in:inbox newer_than:4d -category:promotions -category:social'
messages=api_get(token, 'https://gmail.googleapis.com/gmail/v1/users/me/messages', {'q':query,'maxResults':MAX_RESULTS}).get('messages',[])
scanned=0; inserted=0; skips=Counter(); details=[]; cur=admin.cursor()
for m in messages:
    scanned += 1
    meta=api_get(token, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}", {'format':'metadata','metadataHeaders':['Subject','From','Date']})
    headers=parse_headers(meta.get('payload') or {})
    subject=headers.get('Subject',''); from_header=headers.get('From',''); date_header=headers.get('Date',''); snippet=meta.get('snippet','')
    if cur.execute("SELECT 1 FROM tasks WHERE gmail_message_id=? LIMIT 1", (meta['id'],)).fetchone():
        skips['duplicate_message_id'] += 1; continue
    skip, reason = is_obvious_skip(subject, from_header, snippet)
    if skip and not candidate_by_surface(subject, from_header, snippet):
        skips[reason] += 1; continue
    thread=api_get(token, f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{meta['threadId']}", {'format':'full'})
    resolved, rr = thread_resolved(thread.get('messages',[]))
    if resolved:
        skips[rr] += 1; continue
    full=api_get(token, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}", {'format':'full'})
    text=get_message_text(full)
    actionable, why = evaluate_actionability(subject, from_header, text)
    if not actionable:
        skips[why] += 1; continue
    title=normalize_title(subject, from_header, text)
    if recent_open_similar(cur, from_header, title):
        skips['duplicate_open_similar'] += 1; continue
    description=clean_text((full.get('snippet') or '')[:400])
    source_details=json.dumps({'subject':subject,'from':from_header,'email_date':date_header,'thread_id':meta['threadId']})
    cur.execute("INSERT INTO tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) VALUES (?, ?, ?, ?, 'open', 'gmail', ?, ?)", (title, description, due_date_for(subject,text), priority_for(subject,text), meta['id'], source_details))
    inserted += 1; details.append(f"inserted: {title} | {from_header} | {date_header}")
admin.commit()
print(f'scanned={scanned}')
print(f'inserted={inserted}')
print('skipped=' + ', '.join(f'{k}={v}' for k,v in skips.most_common(10)))
for d in details: print(d)
