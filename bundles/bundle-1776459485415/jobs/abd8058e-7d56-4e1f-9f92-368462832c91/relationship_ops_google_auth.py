import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import requests

DB_PATH = os.environ.get('RELATIONSHIP_OPS_DB_PATH', '').strip()
CLIENT_ID_ENV = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
TOKEN_URL = 'https://oauth2.googleapis.com/token'
PROFILE_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'
JOB_NAME = 'relationship_ops_google_auth'


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect_db():
    if not DB_PATH:
        raise RuntimeError('Missing RELATIONSHIP_OPS_DB_PATH')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def start_run(conn, connection_id):
    run_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO sync_runs (id, connection_id, job_name, status, started_at)
        VALUES (?, ?, ?, 'started', CURRENT_TIMESTAMP)""",
        (run_id, connection_id, JOB_NAME),
    )
    conn.commit()
    return run_id


def finish_run(conn, run_id, status, records_seen=0, records_written=0, error_message=None):
    conn.execute(
        """UPDATE sync_runs
        SET status=?, records_seen=?, records_written=?, error_message=?, finished_at=CURRENT_TIMESTAMP
        WHERE id=?""",
        (status, records_seen, records_written, error_message, run_id),
    )
    conn.commit()


def fail_request(conn, req_id, connection_id, message):
    conn.execute(
        "UPDATE oauth_requests SET status='failed', error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (message[:2000], req_id),
    )
    conn.execute(
        """INSERT INTO connections (id, provider, product, status, last_error, updated_at)
        VALUES (?, 'google', 'google_account', 'error', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET status='error', last_error=excluded.last_error, updated_at=CURRENT_TIMESTAMP""",
        (connection_id, message[:2000]),
    )
    conn.commit()


def get_pending_request(conn):
    return conn.execute(
        """SELECT * FROM oauth_requests
        WHERE provider='google' AND status='pending'
        ORDER BY created_at DESC, id DESC
        LIMIT 1"""
    ).fetchone()


def exchange_code(req):
    client_id = (req['client_id'] or CLIENT_ID_ENV).strip()
    if not client_id:
        raise RuntimeError('Missing Google client ID. Enter it in the app or set GOOGLE_CLIENT_ID.')
    if not CLIENT_SECRET:
        raise RuntimeError('Missing GOOGLE_CLIENT_SECRET key in Papr Work settings.')
    payload = {
        'code': req['auth_code'].strip(),
        'client_id': client_id,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': req['redirect_uri'].strip(),
        'grant_type': 'authorization_code',
    }
    res = requests.post(TOKEN_URL, data=payload, timeout=30)
    if res.status_code >= 400:
        raise RuntimeError(f'Token exchange failed: {res.text}')
    token = res.json()
    if not token.get('access_token'):
        raise RuntimeError(f'No access token returned: {json.dumps(token)}')
    return client_id, token


def fetch_profile(access_token):
    res = requests.get(PROFILE_URL, headers={'Authorization': f'Bearer {access_token}'}, timeout=30)
    if res.status_code >= 400:
        raise RuntimeError(f'Profile fetch failed: {res.text}')
    profile = res.json()
    if not profile.get('sub'):
        raise RuntimeError(f'Profile response missing sub: {json.dumps(profile)}')
    return profile


def save_connection(conn, req, client_id, token, profile):
    connection_id = req['connection_id']
    duplicate = conn.execute(
        "SELECT id, email FROM connections WHERE provider='google' AND external_account_id=? AND id<>? LIMIT 1",
        (profile.get('sub'), connection_id),
    ).fetchone()
    if duplicate:
        other_slot = duplicate['id'].split(':', 1)[-1].replace('primary', 'business').title()
        raise RuntimeError(
            f"This Google account ({duplicate['email'] or profile.get('email') or 'unknown'}) is already connected in the {other_slot} slot. Reset that slot first or sign into a different Google account here."
        )
    scopes_raw = token.get('scope') or req['scopes'] or '[]'
    scopes_json = json.dumps(scopes_raw.split()) if isinstance(scopes_raw, str) else json.dumps(scopes_raw)
    metadata = {
        'picture': profile.get('picture'),
        'email_verified': profile.get('email_verified'),
        'client_id': client_id,
    }
    expires_at = None
    if token.get('expires_in'):
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(token['expires_in']))).isoformat()

    conn.execute(
        """INSERT INTO connections
        (id, provider, product, account_label, external_account_id, email, display_name, status, scopes, metadata_json, last_error, last_sync_at, updated_at)
        VALUES (?, 'google', 'google_account', ?, ?, ?, ?, 'connected', ?, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
          account_label=excluded.account_label,
          external_account_id=excluded.external_account_id,
          email=excluded.email,
          display_name=excluded.display_name,
          status='connected',
          scopes=excluded.scopes,
          metadata_json=excluded.metadata_json,
          last_error=NULL,
          last_sync_at=CURRENT_TIMESTAMP,
          updated_at=CURRENT_TIMESTAMP""",
        (
            connection_id,
            profile.get('email') or profile.get('name') or 'Google Account',
            profile.get('sub'),
            profile.get('email'),
            profile.get('name'),
            scopes_json,
            json.dumps(metadata),
        ),
    )
    conn.execute(
        """INSERT INTO oauth_tokens
        (connection_id, access_token, refresh_token, token_type, expires_at, raw_token_response, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(connection_id) DO UPDATE SET
          access_token=excluded.access_token,
          refresh_token=COALESCE(excluded.refresh_token, oauth_tokens.refresh_token),
          token_type=excluded.token_type,
          expires_at=excluded.expires_at,
          raw_token_response=excluded.raw_token_response,
          updated_at=CURRENT_TIMESTAMP""",
        (
            connection_id,
            token.get('access_token'),
            token.get('refresh_token'),
            token.get('token_type'),
            expires_at,
            json.dumps(token),
        ),
    )
    conn.execute(
        "UPDATE oauth_requests SET status='completed', error_message=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (req['id'],),
    )
    conn.commit()
    return scopes_json


def main():
    conn = connect_db()
    run_id = None
    try:
        req = get_pending_request(conn)
        if not req:
            print('No pending Google auth requests.')
            return
        run_id = start_run(conn, req['connection_id'])
        try:
            client_id, token = exchange_code(req)
            profile = fetch_profile(token['access_token'])
            scopes_json = save_connection(conn, req, client_id, token, profile)
        except Exception as e:
            msg = str(e)
            fail_request(conn, req['id'], req['connection_id'], msg)
            finish_run(conn, run_id, 'failed', 1, 0, msg)
            print(msg)
            return
        finish_run(conn, run_id, 'completed', 1, 3, None)
        print(f"Connected Google account ({req['connection_id']}): {profile.get('email', 'unknown')}")
        print(f"Scopes: {scopes_json}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
