import sqlite3, json, urllib.request, urllib.parse, base64, re, email.utils, datetime
from html import unescape

OAUTH_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
DRY_RUN=False
SKIP_PHRASES=['will provide an update','keep an eye out','we weren\'t able to locate it','sounds good','see you then','thanks got it','thank you, got it','confirmed','extension filed','done','completed','taken care of','scheduled','paid','submitted','final confirmation','payment receipt','receipt','refund is confirmed','subscription canceled','membership was successfully cancelled','we\'re sorry to see you go','accepted:','cancellation','successfully cancelled']
NON_ACTION_SUBJECT=['newsletter','receipt','statement is available','payment receipt','security alert','sign in from a new device','invitation:','accepted:','subscription canceled','successfully cancelled','refund is confirmed','verification code']
ACTION_PATTERNS=[r'\bplease (confirm|review|reply|respond|send|provide|submit|upload|complete|fill out|advise|let me know)\b',r'\bcould you\b',r'\bcan you\b',r'\bi need (a bit more information|you to|more information)\b',r'\baction required\b',r'\bneed your\b',r'\bplease advise\b',r'\blet me know\b',r'\bconfirm the specific item',r'\bdo you have\b',r'\bwe need\b',r'\bwould you be able to\b']
FINANCE_SCORES=[('overdraft',3),('payment due',3),('past due',3),('low balance',2),('alert',1)]

def b64url_decode(data): return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', 'ignore')
def extract_text(payload):
    texts=[]
    def walk(part):
        mt=part.get('mimeType',''); body=part.get('body',{}) or {}; data=body.get('data')
        if data and mt in ('text/plain','text/html'):
            txt=b64url_decode(data)
            if mt=='text/html': txt=re.sub(r'<[^>]+>',' ',txt)
            texts.append(unescape(txt))
        for p in part.get('parts',[]) or []: walk(p)
    walk(payload or {})
    return re.sub(r'\s+',' ',' '.join(texts)).strip()[:15000]
def get_headers(msg): return {h['name']:h['value'] for h in msg.get('payload',{}).get('headers',[])}
def parse_from(h):
    name, addr = email.utils.parseaddr(h or '')
    return (name or addr or '').strip(), (addr or '').strip().lower()
def parse_date(h, ms):
    if h:
        try:
            dt=email.utils.parsedate_to_datetime(h)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
        except Exception: pass
    return datetime.datetime.fromtimestamp(int(ms)/1000, datetime.timezone.utc)
def api(token, path):
    req=urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/'+path, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
def norm(s): return re.sub(r'\s+',' ',(s or '').strip())
def classify_title(subject, from_name, from_email, text):
    sender=(from_name or from_email.split('@')[0] or 'sender').strip('" ')
    sl=((subject or '')+' '+text[:500]).lower()
    if any(k in sl for k,_ in FINANCE_SCORES):
        return (f"Make a payment: {sender}" if any(k in sl for k in ['payment due','past due','overdraft']) else f"Review finance alert: {sender}",1)
    if 'secure message' in sl: return (f"Respond to secure message: {sender}",2)
    if any(k in sl for k in ['legal','order of child support','motion for reconsideration','new orders filed','court','filing']): return (f"Review legal filing: {sender}",1)
    if any(k in sl for k in ['appointment','telehealth']) and any(k in sl for k in ['confirm','verification','complete forms','paperwork']): return (f"Confirm appointment: {sender}",2)
    if any(k in sl for k in ['support request','membership & billing','cancel membership']): return (f"Respond to message: {sender.replace(' Support','')}",2)
    if any(k in sl for k in ['upload','document']) and any(k in sl for k in ['please','need','required','review','send','provide']): return (f"Upload document: {sender}",2)
    if any(k in sl for k in ['form','application']) and any(k in sl for k in ['submit','complete','fill out']): return (f"Submit form: {sender}",2)
    if any(k in sl for k in ['review','attached','document','filing']) and any(k in sl for k in ['please','need','required']): return (f"Review document: {sender}",2)
    if any(k in sl for k in ['send','provide','bank statement','information','details']): return (f"Send information: {sender}",2)
    return (f"Respond to message: {sender}",2)
def ask_detected(subject, text):
    sl=((subject or '')+' '+(text or '')[:4000]).lower()
    if any(bad in sl for bad in NON_ACTION_SUBJECT): return False
    if any(p in sl for p in ['reply to this email to update the support request','looking forward to hearing from you']): return True
    return any(re.search(p, sl) for p in ACTION_PATTERNS)
def closure_detected(subject, text):
    sl=((subject or '')+' '+(text or '')[:4000]).lower()
    return any(p in sl for p in SKIP_PHRASES)
def summarize(text):
    return re.sub(r'On .* wrote:.*','',norm(text))[:280]

conn=sqlite3.connect(OAUTH_DB); cur=conn.cursor(); cur.execute("select c.email, t.access_token from connections c join oauth_tokens t on c.id=t.connection_id where c.id='google:personal'")
user_email, token = cur.fetchone(); user_emails={user_email.lower()}
query='in:inbox newer_than:4d -category:promotions -category:social -in:spam -in:trash'
thread_ids=[]; page=None
while True:
    path='messages?q='+urllib.parse.quote(query)+'&maxResults=100' + ('&pageToken='+urllib.parse.quote(page) if page else '')
    data=api(token, path)
    for m in data.get('messages',[]) or []:
        if m.get('threadId'): thread_ids.append(m['threadId'])
    page=data.get('nextPageToken')
    if not page: break
thread_ids=list(dict.fromkeys(thread_ids))
admin=sqlite3.connect(ADMIN_DB); admin.row_factory=sqlite3.Row; ac=admin.cursor()
scanned=0; skips={}; candidates=[]
def skip(r): skips[r]=skips.get(r,0)+1
def has_existing(msg_id, thread_id, sender_email, title):
    if ac.execute("select 1 from tasks where source='gmail' and gmail_message_id=? limit 1", (msg_id,)).fetchone(): return 'duplicate_message_id'
    if ac.execute("select 1 from tasks where source='gmail' and status='open' and datetime(created_at) >= datetime('now','-10 days') and lower(json_extract(source_details,'$.thread_id'))=? limit 1", (thread_id.lower(),)).fetchone(): return 'open_thread_task_exists'
    if ac.execute("select 1 from tasks where source='gmail' and status='open' and datetime(created_at) >= datetime('now','-10 days') and lower(json_extract(source_details,'$.from')) like ? and lower(title)=lower(?) limit 1", ('%'+sender_email.lower()+'%', title)).fetchone(): return 'open_similar_task_exists'
    return None
for tid in thread_ids:
    scanned += 1
    thread=api(token, f'threads/{urllib.parse.quote(tid)}?format=full')
    msgs=[]
    for m in thread.get('messages',[]) or []:
        h=get_headers(m); from_name, from_email=parse_from(h.get('From','')); dt=parse_date(h.get('Date',''), m.get('internalDate','0')); text=extract_text(m.get('payload',{})) or m.get('snippet','') or ''
        msgs.append({'id':m['id'],'thread_id':thread.get('id',tid),'subject':h.get('Subject',''),'from_name':from_name,'from_email':from_email,'date_hdr':h.get('Date',''),'dt':dt,'text':text,'snippet':m.get('snippet',''),'inbound': from_email not in user_emails})
    msgs.sort(key=lambda x:x['dt'])
    if not msgs: skip('empty_thread'); continue
    latest=msgs[-1]
    if not latest['inbound']: skip('latest_message_from_user'); continue
    subj_l=latest['subject'].lower()
    if closure_detected(latest['subject'], latest['text']): skip('resolved_or_confirmation'); continue
    if any(s in subj_l for s in NON_ACTION_SUBJECT) and not ask_detected(latest['subject'], latest['text']): skip('notification_or_receipt'); continue
    if not ask_detected(latest['subject'], latest['text']): skip('no_explicit_action'); continue
    last_inbound=max(i for i,m in enumerate(msgs) if m['inbound'])
    if any((not m['inbound']) and m['dt']>msgs[last_inbound]['dt'] for m in msgs): skip('already_replied'); continue
    title, priority=classify_title(latest['subject'], latest['from_name'], latest['from_email'], latest['text'])
    dup=has_existing(latest['id'], latest['thread_id'], latest['from_email'], title)
    if dup: skip(dup); continue
    candidates.append({'gmail_message_id':latest['id'],'thread_id':latest['thread_id'],'from':(f"{latest['from_name']} <{latest['from_email']}>" if latest['from_name'] else latest['from_email']),'from_email':latest['from_email'],'subject':latest['subject'],'email_date':latest['date_hdr'] or latest['dt'].isoformat(),'title':title,'description':summarize(latest['text'] or latest['snippet']),'priority':priority,'due_date':None,'day':latest['dt'].date().isoformat(),'text':latest['text']})
bykey={}; filtered=[]
for c in candidates:
    sl=(c['subject']+' '+c['text'][:500]).lower()
    if any(k in sl for k,_ in FINANCE_SCORES):
        score=max((score for k,score in FINANCE_SCORES if k in sl), default=0); key=(c['from_email'], c['day']); prev=bykey.get(key)
        if prev is None or score > prev[0]: bykey[key]=(score,c)
    else: filtered.append(c)
keep={id(v[1]) for v in bykey.values()}
for c in candidates:
    sl=(c['subject']+' '+c['text'][:500]).lower()
    if any(k in sl for k,_ in FINANCE_SCORES):
        if id(c) in keep: filtered.append(c)
        else: skip('weaker_finance_alert')
print('scanned_count=%d' % scanned)
inserted=0
for c in filtered:
    ac.execute("insert into tasks (title, description, due_date, priority, status, source, gmail_message_id, source_details) values (?,?,?,?, 'open','gmail',?,?)", (c['title'], c['description'], c['due_date'], c['priority'], c['gmail_message_id'], json.dumps({'subject': c['subject'], 'from': c['from'], 'email_date': c['email_date'], 'thread_id': c['thread_id']})))
    inserted += 1
admin.commit()
print('inserted_count=%d' % inserted)
print('candidate_count=%d' % len(filtered))
for c in filtered[:30]: print('CANDIDATE|%s|%s|%s|%s' % (c['gmail_message_id'], c['title'], c['from'], c['subject']))
print('skipped=' + json.dumps(skips, sort_keys=True))
