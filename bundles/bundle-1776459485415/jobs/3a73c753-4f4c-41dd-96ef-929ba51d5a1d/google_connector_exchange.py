import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'data', 'data.db')
TOKEN_URL = 'https://oauth2.googleapis.com/token'
PROFILE_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'
CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()


def utc_now():
    return datetime.now(timezone.utc)


def ensure_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS google_auth_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      client_id TEXT,
      redirect_uri TEXT NOT NULL,
      scopes TEXT NOT NULL,
      auth_code TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      exchange_error TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS google_connections (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      google_user_id TEXT UNIQUE NOT NULL,
      email TEXT NOT NULL,
      name TEXT,
      picture TEXT,
      scopes TEXT NOT NULL,
      access_token TEXT NOT NULL,
      refresh_token TEXT,
      token_type TEXT,
      expires_at TEXT,
      connected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_auth_requests_status ON google_auth_requests(status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_google_connections_email ON google_connections(email);
    ''')
    conn.commit()


def fail_request(conn, req_id, message):
    conn.execute(
        "UPDATE google_auth_requests SET status='failed', exchange_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (message[:800], req_id),
    )
    conn.commit()
    print(message)


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    req = conn.execute(
        "SELECT * FROM google_auth_requests WHERE status='pending' ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if not req:
        total = conn.execute('SELECT COUNT(*) AS n FROM google_connections').fetchone()['n']
        print(f'No pending auth requests. Stored connections: {total}')
        return
    if not CLIENT_SECRET:
        fail_request(conn, req['id'], 'Missing GOOGLE_CLIENT_SECRET key in Papr Work settings.')
        return
    client_id = (req['client_id'] or CLIENT_ID).strip()
    if not client_id:
        fail_request(conn, req['id'], 'Missing Google client ID. Add GOOGLE_CLIENT_ID key or enter it in the app form.')
        return
    payload = {
        'code': req['auth_code'].strip(),
        'client_id': client_id,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': req['redirect_uri'].strip(),
        'grant_type': 'authorization_code',
    }
    token_res = requests.post(TOKEN_URL, data=payload, timeout=30)
    if token_res.status_code >= 400:
        fail_request(conn, req['id'], f'Token exchange failed: {token_res.text}')
        return
    token = token_res.json()
    access_token = token.get('access_token')
    if not access_token:
        fail_request(conn, req['id'], f'No access token returned: {json.dumps(token)}')
        return
    profile_res = requests.get(PROFILE_URL, headers={'Authorization': f'Bearer {access_token}'}, timeout=30)
    if profile_res.status_code >= 400:
        fail_request(conn, req['id'], f'Profile fetch failed: {profile_res.text}')
        return
    profile = profile_res.json()
    expires_at = None
    if token.get('expires_in'):
        expires_at = (utc_now() + timedelta(seconds=int(token['expires_in']))).isoformat()
    scopes = token.get('scope') or req['scopes']
    conn.execute(
        '''INSERT INTO google_connections
        (google_user_id, email, name, picture, scopes, access_token, refresh_token, token_type, expires_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(google_user_id) DO UPDATE SET
          email=excluded.email, name=excluded.name, picture=excluded.picture, scopes=excluded.scopes,
          access_token=excluded.access_token, refresh_token=COALESCE(excluded.refresh_token, google_connections.refresh_token),
          token_type=excluded.token_type, expires_at=excluded.expires_at, updated_at=CURRENT_TIMESTAMP''',
        (
            profile.get('sub', ''), profile.get('email', ''), profile.get('name'), profile.get('picture'),
            scopes, access_token, token.get('refresh_token'), token.get('token_type'), expires_at,
        ),
    )
    conn.execute(
        "UPDATE google_auth_requests SET status='completed', exchange_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (req['id'],),
    )
    conn.commit()
    print(f"Connected Google account: {profile.get('email', 'unknown')} at {datetime.utcnow().isoformat()}Z")


if __name__ == '__main__':
    main()
