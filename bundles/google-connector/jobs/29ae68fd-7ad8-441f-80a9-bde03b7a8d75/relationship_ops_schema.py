import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'data.db'

SCHEMA = '''
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  product TEXT NOT NULL,
  account_label TEXT,
  external_account_id TEXT,
  email TEXT,
  display_name TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  scopes TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_sync_at TEXT,
  last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_connections_provider_product ON connections(provider, product);

CREATE TABLE IF NOT EXISTS oauth_tokens (
  connection_id TEXT PRIMARY KEY,
  access_token TEXT,
  refresh_token TEXT,
  token_type TEXT,
  expires_at TEXT,
  raw_token_response TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS oauth_requests (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  client_id TEXT,
  redirect_uri TEXT NOT NULL,
  scopes TEXT NOT NULL DEFAULT '[]',
  auth_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_oauth_requests_provider_status ON oauth_requests(provider, status, created_at DESC);

CREATE TABLE IF NOT EXISTS sync_runs (
  id TEXT PRIMARY KEY,
  connection_id TEXT,
  job_name TEXT NOT NULL,
  status TEXT NOT NULL,
  cursor_value TEXT,
  records_seen INTEGER NOT NULL DEFAULT 0,
  records_written INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  error_message TEXT,
  FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_job_name ON sync_runs(job_name, started_at DESC);

CREATE TABLE IF NOT EXISTS people (
  id TEXT PRIMARY KEY,
  full_name TEXT,
  primary_email TEXT,
  company_name TEXT,
  linkedin_url TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_people_email ON people(primary_email);

CREATE TABLE IF NOT EXISTS person_identities (
  id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  external_id TEXT,
  email TEXT,
  profile_url TEXT,
  raw_ref TEXT,
  FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_person_identities_lookup ON person_identities(provider, email, external_id);

CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  domain TEXT,
  crm_external_id TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);

CREATE TABLE IF NOT EXISTS activities (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  activity_type TEXT NOT NULL,
  external_id TEXT,
  connection_id TEXT,
  occurred_at TEXT NOT NULL,
  title TEXT,
  summary TEXT,
  body_text TEXT,
  direction TEXT,
  status TEXT,
  source_url TEXT,
  raw_payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_occurred_at ON activities(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_activities_provider_type ON activities(provider, activity_type);

CREATE TABLE IF NOT EXISTS activity_participants (
  id TEXT PRIMARY KEY,
  activity_id TEXT NOT NULL,
  role TEXT,
  email TEXT,
  display_name TEXT,
  person_id TEXT,
  company_id TEXT,
  match_confidence REAL,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_participants_activity ON activity_participants(activity_id);
CREATE INDEX IF NOT EXISTS idx_activity_participants_email ON activity_participants(email);

CREATE TABLE IF NOT EXISTS crm_records (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  record_type TEXT NOT NULL,
  external_id TEXT NOT NULL,
  display_label TEXT,
  person_id TEXT,
  company_id TEXT,
  raw_payload TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE SET NULL,
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_records_unique ON crm_records(provider, record_type, external_id);

CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  activity_id TEXT,
  crm_provider TEXT NOT NULL,
  target_record_id TEXT,
  proposal_type TEXT NOT NULL,
  reason TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  confidence REAL,
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TEXT,
  applied_at TEXT,
  FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE SET NULL,
  FOREIGN KEY (target_record_id) REFERENCES crm_records(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status, created_at DESC);

CREATE TABLE IF NOT EXISTS proposal_evidence (
  id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  content TEXT NOT NULL,
  FOREIGN KEY (proposal_id) REFERENCES proposals(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_proposal_evidence_proposal ON proposal_evidence(proposal_id);
'''

TABLES = [
    'connections', 'oauth_tokens', 'oauth_requests', 'sync_runs', 'people', 'person_identities',
    'companies', 'activities', 'activity_participants', 'crm_records',
    'proposals', 'proposal_evidence'
]


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    print(f"Relationship Ops schema ready: {DB_PATH}")
    for table, count in counts.items():
        print(f"- {table}: {count}")


if __name__ == '__main__':
    main()
