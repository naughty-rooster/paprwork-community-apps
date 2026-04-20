import os, sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'data.db')
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
conn = sqlite3.connect(DB_PATH)
conn.executescript("""
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, description TEXT, due_date TEXT, priority INTEGER DEFAULT 2,
  status TEXT DEFAULT 'open', source TEXT DEFAULT 'manual', gmail_message_id TEXT,
  source_details TEXT, tags TEXT, created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')), snoozed_until TEXT
);
CREATE TABLE IF NOT EXISTS daily_digests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL UNIQUE, summary TEXT,
  task_ids TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS message_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT, message_guid TEXT NOT NULL UNIQUE,
  chat_identifier TEXT, contact TEXT, message_text TEXT NOT NULL, message_date TEXT,
  score REAL DEFAULT 0, status TEXT DEFAULT 'new', source_details TEXT,
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS recurring_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT,
  priority INTEGER DEFAULT 2, frequency TEXT NOT NULL DEFAULT 'weekly', interval_n INTEGER DEFAULT 1,
  start_date TEXT NOT NULL, next_due_date TEXT NOT NULL, weekday INTEGER, day_of_month INTEGER,
  status TEXT DEFAULT 'active', source_details TEXT, created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source);
CREATE INDEX IF NOT EXISTS idx_message_candidates_status ON message_candidates(status);
CREATE INDEX IF NOT EXISTS idx_message_candidates_date ON message_candidates(message_date);
CREATE INDEX IF NOT EXISTS idx_recurring_status_due ON recurring_templates(status, next_due_date);
""")
for sql in [
  "ALTER TABLE projects ADD COLUMN planning_status TEXT DEFAULT 'idle'",
  "ALTER TABLE projects ADD COLUMN planning_requested_at TEXT",
  "ALTER TABLE projects ADD COLUMN planning_summary TEXT"
]:
  try: conn.execute(sql)
  except sqlite3.OperationalError: pass
conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_planning ON projects(planning_status, planning_requested_at)")
conn.commit(); conn.close()
print('DB schema created/verified OK')
print(f'DB path: {os.path.abspath(DB_PATH)}')
