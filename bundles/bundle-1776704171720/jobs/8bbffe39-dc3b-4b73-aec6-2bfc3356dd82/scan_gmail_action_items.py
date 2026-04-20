import base64,json,re,sqlite3,urllib.parse,urllib.request
from collections import Counter
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime,parseaddr
GOOGLE_DB='/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db'
ADMIN_DB='/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db'
Q='in:inbox newer_than:4d -category:promotions -category:social'
LIST='https://gmail.googleapis.com/gmail/v1/users/me/messages'
THREAD='https://gmail.googleapis.com/gmail/v1/users/me/threads/{}'
SKIP=['verification code','mfa code','authentication code','one-time sign in link','payment confirmation','payment scheduled','order receipt','charged','receipt','newsletter','promo','marketing','activate your streaming subscriptions','automatic reply','out of office','will provide an update','keep an eye out',"we weren't able to locate",'sounds good','see you then','your account statement is here','telehealth verification code','teacher appreciation week']
ACT=['please advise','please review','please take a look','please confirm','please reply','please respond','please submit','please upload','please send','action required','let me know what works','can you','could you','need you to','you need to','required to','payment due','review the attached','take a look at it','update your account password',"wasn't you?"]
DONE=['confirmed','filed','extension filed','done','completed','taken care of','scheduled','sounds good','see you then','paid','submitted','thanks got it','thank you for scheduling','payment confirmation','thank you for your recent',"okay he's scheduled",'will provide an update','keep an eye out',"we weren't able to locate"]
MONTHS={m:i for i,m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'],1)}
clean=lambda s:re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',s or '')).strip()
def dec(d):
 d=(d or '')
 if not d:return ''
 d+='='*(-len(d)%4)
 try:return base64.urlsafe_b64decode(d.encode()).decode('utf-8','ignore')
 except:return ''
def text(p):
 mt=(p.get('mimeType') or '').lower()
 if mt=='text/plain':return clean(dec((p.get('body') or {}).get('data')))
 if mt=='text/html':return clean(dec((p.get('body') or {}).get('data')))
 return clean(' '.join(filter(None,[text(x) for x in (p.get('parts') or [])])))
def hdr(p,n):
 for h in p.get('headers') or []:
  if h.get('name','').lower()==n.lower():return h.get('value','')
 return ''
def dtmsg(m):
 try:return datetime.fromtimestamp(int(m.get('internalDate','0'))/1000,tz=timezone.utc)
 except:pass
 try:return parsedate_to_datetime(hdr(m.get('payload',{}),'Date')).astimezone(timezone.utc)
 except:return datetime.now(timezone.utc)
def s_email(f):return (parseaddr(f or '')[1] or '').lower()
def s_name(f):
 n,a=parseaddr(f or '')
 return clean(n or a.split('@')[0] or a)
def get(url,token,params=None):
 if params:url+='?'+urllib.parse.urlencode(params,doseq=True)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':f'Bearer {token}'}),timeout=30) as r:return json.load(r)
conn=sqlite3.connect(f'file:{GOOGLE_DB}?mode=ro',uri=True);conn.row_factory=sqlite3.Row
row=conn.execute("SELECT c.email,t.access_token FROM connections c JOIN oauth_tokens t ON t.connection_id=c.id WHERE c.id='google:personal'").fetchone();conn.close()
me=row['email'].lower();token=row['access_token']
refs=[];page=None
while len(refs)<100:
 params={'q':Q,'maxResults':min(100,100-len(refs))}
 if page:params['pageToken']=page
 data=get(LIST,token,params);refs.extend(data.get('messages') or []);page=data.get('nextPageToken')
 if not page:break
thread_to_msg={}
for r in refs: thread_to_msg.setdefault(r['threadId'],r['id'])
aconn=sqlite3.connect(ADMIN_DB);aconn.row_factory=sqlite3.Row
rows=aconn.execute("SELECT id,title,status,gmail_message_id,source_details,created_at FROM tasks WHERE source='gmail'").fetchall()
existing=[]
for r in rows:
 try:details=json.loads(r['source_details'] or '{}')
 except:details={}
 existing.append({'id':r['id'],'title':r['title'],'status':r['status'],'msg':r['gmail_message_id'],'details':details,'created':r['created_at']})
existing_ids={x['msg'] for x in existing if x['msg']}
skip=Counter();cands=[];scanned=0
for tid,mid in thread_to_msg.items():
 scanned+=1
 th=get(THREAD.format(tid),token,{'format':'full'})
 msgs=[]
 for m in th.get('messages') or []:
  p=m.get('payload',{})
  msgs.append({'id':m['id'],'thread_id':tid,'dt':dtmsg(m),'subject':hdr(p,'Subject'),'from':hdr(p,'From'),'from_email':s_email(hdr(p,'From')),'text':text(p) or m.get('snippet','')})
 msgs.sort(key=lambda x:x['dt'])
 c=next((m for m in reversed(msgs) if m['id']==mid),msgs[-1] if msgs else None)
 if not c:skip['no_candidate']+=1;continue
 combo=(c['subject']+' '+c['text']).lower()
 if not c['from_email'] or c['from_email']==me:skip['not_inbound']+=1;continue
 if any(x in combo for x in SKIP):skip['noise_or_notification']+=1;continue
 if 'noreply' in c['from_email'] and not any(x in combo for x in ['please review','please take a look','action required','update your account password']):skip['no_reply_notification']+=1;continue
 later=[m for m in msgs if m['dt']>c['dt']]
 if later:
  latest=later[-1];lcombo=(latest['subject']+' '+latest['text']).lower()
  if latest['from_email']==me:skip['resolved_by_user_reply']+=1;continue
  if any(x in lcombo for x in DONE):skip['resolved_in_later_message']+=1;continue
 if not(any(x in combo for x in ACT) or ('please' in combo and any(w in combo for w in ['review','confirm','reply','respond','send','submit','upload','take a look']))):
  skip['no_explicit_ask']+=1;continue
 subj=c['subject'].lower();body=c['text'].lower();org=s_name(c['from'])
 if ('payment' in body or 'payment due' in subj): title=f'Make a payment: {org}'
 elif 'order' in subj and 'case' in subj: title='Review legal filing: de Maar Law' if ('demaarlaw' in c['from_email'] or 'april beck' in c['from'].lower()) else f'Review legal filing: {org}'
 elif 'document from' in subj or 'progress note' in body or 'review the attached' in body: title=f'Review document: {org}'
 elif 'telehealth' in subj and ('confirm' in body or 'reply' in body): title=f'Confirm appointment: {org}'
 elif 'upload' in body: title=f'Upload document: {org}'
 elif any(x in body for x in ['please send','send me','send us']): title=f'Send information: {org}'
 elif any(x in body for x in ['follow up','check in','let me know']): title=f'Follow up with: {org}'
 else: title=f'Respond to message: {org}'
 if c['id'] in existing_ids:skip['duplicate_message_id']+=1;continue
 dup=False
 tw=set(re.findall(r'[a-z0-9]+',title.lower()))
 for e in existing:
  if e['status']!='open':continue
  if s_email(e['details'].get('from',''))!=c['from_email']:continue
  if (e['created'] or '') < (datetime.utcnow()-timedelta(days=14)).strftime('%Y-%m-%d'):continue
  ew=set(re.findall(r'[a-z0-9]+',(e['title'] or '').lower()))
  if len(tw & ew)>=2 or e['details'].get('thread_id')==tid: dup=True; break
 if dup:skip['similar_open_task']+=1;continue
 cands.append((c,title))
# finance de-dupe
bykey={};chosen=[]
for c,title in cands:
 combo=(c['subject']+' '+c['text']).lower()
 if any(x in combo for x in ['balance','overdraft','payment due','payment failed']):
  key=f"{c['from_email']}|{c['dt'].date().isoformat()}|finance"
  score=max([v for k,v in [('low balance',1),('payment due',2),('overdraft',3),('past due',3),('payment failed',4)] if k in combo] or [0])
  if key not in bykey or score>bykey[key][2]: bykey[key]=(c,title,score)
 else: chosen.append((c,title))
chosen.extend((v[0],v[1]) for v in bykey.values())
inserted=[]
for c,title in chosen:
 combo=(c['subject']+' '+c['text']).lower(); due=None
 if 'today' in combo: due=c['dt'].date().isoformat()
 elif 'tomorrow' in combo: due=(c['dt'].date()+timedelta(days=1)).isoformat()
 else:
  m=re.search(r'\b('+'|'.join(MONTHS.keys())+r')\s+(\d{1,2})(?:,\s*(\d{4}))?\b',combo)
  if m:
   try: due=datetime(int(m.group(3) or c['dt'].year),MONTHS[m.group(1)],int(m.group(2))).date().isoformat()
   except: due=None
 pr=1 if any(x in combo for x in ['urgent','asap','immediately','update your account password',"wasn't you?"]) else 2
 details=json.dumps({'subject':c['subject'],'from':c['from'],'email_date':c['dt'].isoformat(),'thread_id':c['thread_id']})
 aconn.execute("INSERT INTO tasks (title,description,due_date,priority,status,source,gmail_message_id,source_details,created_at,updated_at) VALUES (?,?,?,?, 'open','gmail',?,?,datetime('now'),datetime('now'))",(title,clean(c['text'])[:500],due,pr,c['id'],details))
 inserted.append(title)
aconn.commit();aconn.close()
print(json.dumps({'scanned_count':scanned,'inserted_count':len(inserted),'inserted_titles':inserted,'skipped_reasons':dict(skip)},indent=2))
