import json, os, re, sqlite3
from datetime import datetime, timedelta, timezone
import requests
GOOGLE_DB="/Users/coreybadcock/Papr/jobs/29ae68fd-7ad8-441f-80a9-bde03b7a8d75/data/data.db"
ADMIN_DB="/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db"
TOKEN_URL="https://oauth2.googleapis.com/token"
EVENTS_URL="https://www.googleapis.com/calendar/v3/calendars/primary/events"
CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET","").strip()
SKIP_RE=re.compile(r"(birthday|holiday|focus time|out of office|ooo|hold|blocked)",re.I)

def token():
    c=sqlite3.connect(GOOGLE_DB); c.row_factory=sqlite3.Row
    r=c.execute("SELECT c.email,c.metadata_json,t.access_token,t.refresh_token,t.expires_at FROM connections c JOIN oauth_tokens t ON t.connection_id=c.id WHERE c.id='google:personal'").fetchone()
    if not r: raise RuntimeError('No personal Google connection found.')
    meta=json.loads(r['metadata_json'] or '{}'); at=(r['access_token'] or '').strip(); rt=(r['refresh_token'] or '').strip(); ex=(r['expires_at'] or '').strip()
    try: needs=datetime.fromisoformat(ex.replace('Z','+00:00'))<=datetime.now(timezone.utc)+timedelta(minutes=5)
    except: needs=True
    if needs and rt:
        x=requests.post(TOKEN_URL,data={'client_id':meta.get('client_id','').strip(),'client_secret':CLIENT_SECRET,'refresh_token':rt,'grant_type':'refresh_token'},timeout=30); x.raise_for_status()
        at=x.json()['access_token']; exp=datetime.now(timezone.utc)+timedelta(seconds=x.json().get('expires_in',3600))
        c.execute("UPDATE oauth_tokens SET access_token=?,expires_at=?,updated_at=CURRENT_TIMESTAMP WHERE connection_id='google:personal'",(at,exp.isoformat())); c.commit()
    c.close(); return at,r['email']

def parse_start(ev):
    raw=(ev.get('start') or {}).get('dateTime') or (ev.get('start') or {}).get('date')
    if not raw: return None,None
    if 'T' not in raw: return raw, raw
    dt=datetime.fromisoformat(raw.replace('Z','+00:00')); return dt.date().isoformat(), dt.astimezone().strftime('%a %b %d %I:%M %p')

def keep(ev):
    s=(ev.get('summary') or 'Untitled event').strip()
    return ev.get('status')!='cancelled' and s and not SKIP_RE.search(s)

def item(ev, existing=None):
    event_date,starts_at=parse_start(ev)
    meta=dict(existing or {})
    description=(ev.get('description') or '').strip()
    meta.update({'event_id':ev.get('id'),'summary':ev.get('summary'),'starts_at':starts_at,'htmlLink':ev.get('htmlLink'),'description':description or meta.get('description',''),'calendar_source':'google-sync'})
    if 'Created by Personal Admin Assistant' in description:
        meta['app_created']=True
    return (ev.get('summary') or 'Untitled event').strip(), event_date, starts_at, ev.get('location'), ev.get('htmlLink'), json.dumps(meta)

def main():
    at,email=token(); now=datetime.now(timezone.utc); end=now+timedelta(days=10)
    r=requests.get(EVENTS_URL,headers={'Authorization':f'Bearer {at}'},params={'singleEvents':'true','orderBy':'startTime','timeMin':now.isoformat(),'timeMax':end.isoformat(),'maxResults':50},timeout=30); r.raise_for_status()
    c=sqlite3.connect(ADMIN_DB)
    c.execute('''CREATE TABLE IF NOT EXISTS calendar_items (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,event_date TEXT,starts_at TEXT,location TEXT,html_link TEXT,source_details TEXT,created_at TEXT DEFAULT (datetime('now')),updated_at TEXT DEFAULT (datetime('now')))''')
    rows=[]
    for e in (r.json().get('items') or []):
        if not keep(e):
            continue
        old=c.execute("SELECT source_details FROM calendar_items WHERE json_extract(source_details,'$.event_id')=?",(e.get('id'),)).fetchone()
        existing=json.loads(old[0] or '{}') if old and old[0] else {}
        rows.append(item(e, existing))
    seen=[]
    for title,event_date,starts_at,location,html_link,details in rows:
        event_id=json.loads(details)['event_id']; seen.append(event_id)
        old=c.execute("SELECT id FROM calendar_items WHERE json_extract(source_details,'$.event_id')=?",(event_id,)).fetchone()
        if old: c.execute("UPDATE calendar_items SET title=?,event_date=?,starts_at=?,location=?,html_link=?,source_details=?,updated_at=datetime('now') WHERE id=?",(title,event_date,starts_at,location,html_link,details,old[0]))
        else: c.execute("INSERT INTO calendar_items (title,event_date,starts_at,location,html_link,source_details) VALUES (?,?,?,?,?,?)",(title,event_date,starts_at,location,html_link,details))
    if seen: c.execute(f"DELETE FROM calendar_items WHERE json_extract(source_details,'$.event_id') NOT IN ({','.join('?'*len(seen))})",seen)
    c.commit(); c.close(); print(f'Calendar sync for {email}: {len(rows)} items up to date')
if __name__=='__main__': main()
