#!/usr/bin/env python3
"""X Feed Fetcher v3 — Bird CLI with auth tokens + own tweet style examples

Fetches:
1. Home timeline (curated by X algorithm)
2. Topic searches (AI/agents/memory/PLG)
3. YOUR OWN recent tweets (replies+quotes) → stored as style examples for scorer

Passes --auth-token and --ct0 to bird CLI for auth.
"""
import os, sys, json, sqlite3, subprocess, logging, math
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

JOB_DIR = Path(os.environ.get('JOB_DIR', Path(__file__).parent.parent))
DB_PATH = JOB_DIR / "data" / "data.db"

AUTH_TOKEN = os.environ.get('X_AUTH_TOKEN', '')
CT0 = os.environ.get('X_CT0', '')

def detect_x_username():
    """Auto-detect X handle via bird whoami."""
    import re
    try:
        result = subprocess.run(['bird', 'whoami'], capture_output=True, text=True, timeout=15)
        for line in result.stdout.splitlines():
            m = re.search(r'@(\w+)', line)
            if m:
                return m.group(1)
    except Exception as e:
        log.warning(f'bird whoami failed: {e}')
    return os.environ.get('X_USERNAME', 'amirkabbara')

YOUR_USERNAME = detect_x_username()
log.info(f'Detected X username: @{YOUR_USERNAME}')

DEFAULT_TOPICS = [
    "AI agents memory", "LLM memory RAG", "agent infrastructure",
    "AI developer tools", "open source AI", "building AI startup",
    "developer PLG growth", "AI agents 2025", "LLM application",
]
FETCH_PER_TOPIC = 8

def setup_database():
    (JOB_DIR / "data").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY, text TEXT NOT NULL,
            author_username TEXT, author_name TEXT, author_id TEXT,
            created_at TEXT, reply_count INTEGER DEFAULT 0,
            retweet_count INTEGER DEFAULT 0, like_count INTEGER DEFAULT 0,
            conversation_id TEXT, in_reply_to_id TEXT, media_url TEXT,
            search_topic TEXT, source TEXT DEFAULT 'search',
            score REAL DEFAULT 0, score_reason TEXT, status TEXT DEFAULT 'new',
            draft_reply TEXT, fetched_at TEXT DEFAULT (datetime('now')),
            acted_at TEXT, author_profile_image TEXT,
            score_type TEXT DEFAULT 'give_value', draft_quote TEXT,
            papr_context TEXT, scored_at TEXT,
            velocity_score REAL DEFAULT 0, hours_old REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mentions (
            id TEXT PRIMARY KEY, text TEXT NOT NULL,
            author_username TEXT, author_name TEXT, author_id TEXT,
            created_at TEXT, reply_count INTEGER DEFAULT 0,
            retweet_count INTEGER DEFAULT 0, like_count INTEGER DEFAULT 0,
            conversation_id TEXT, in_reply_to_id TEXT,
            status TEXT DEFAULT 'new', draft_reply TEXT,
            fetched_at TEXT DEFAULT (datetime('now')), acted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS my_style_tweets (
            id TEXT PRIMARY KEY, text TEXT NOT NULL,
            tweet_type TEXT DEFAULT 'original',
            like_count INTEGER DEFAULT 0, retweet_count INTEGER DEFAULT 0,
            reply_count INTEGER DEFAULT 0, engagement INTEGER DEFAULT 0,
            created_at TEXT, fetched_at TEXT DEFAULT (datetime('now')),
            quoted_tweet_text TEXT, in_reply_to_text TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tweets_status ON tweets(status);
        CREATE INDEX IF NOT EXISTS idx_tweets_score ON tweets(score DESC);
        CREATE INDEX IF NOT EXISTS idx_style_eng ON my_style_tweets(engagement DESC);
    """)
    # Seed default topics if none exist
    existing = conn.execute("SELECT value FROM settings WHERE key='topics'").fetchone()
    if not existing:
        conn.execute("INSERT INTO settings (key, value) VALUES ('topics', ?)",
                     (json.dumps(DEFAULT_TOPICS),))
    conn.commit()
    return conn

def load_topics(conn):
    """Load search topics from settings table, fallback to defaults."""
    row = conn.execute("SELECT value FROM settings WHERE key='topics'").fetchone()
    if row:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            pass
    return DEFAULT_TOPICS

def run_bird(args):
    cmd = ["bird"] + args + ["--json"]
    if AUTH_TOKEN: cmd += ["--auth-token", AUTH_TOKEN]
    if CT0: cmd += ["--ct0", CT0]
    log.info(f"Running: bird {args[0]} ...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.warning(f"bird exit {result.returncode}: {result.stderr[:200]}")
            return []
        if not result.stdout.strip(): return []
        raw = json.loads(result.stdout)
        if isinstance(raw, dict):
            return raw.get("tweets", raw.get("results", []))
        return raw
    except subprocess.TimeoutExpired:
        log.warning("bird timed out"); return []
    except json.JSONDecodeError as e:
        log.warning(f"JSON parse failed: {e}"); return []

AI_KEYWORDS = {
    'ai', 'llm', 'agent', 'agents', 'memory', 'rag', 'model', 'gpt', 'claude',
    'openai', 'anthropic', 'ml', 'machine learning', 'neural',
    'embedding', 'vector', 'inference', 'prompt', 'token', 'context',
    'papr', 'developer', 'dev tools', 'open source', 'github', 'api', 'sdk',
    'startup', 'founder', 'building', 'ship', 'product', 'saas', 'plg',
    'mcp', 'agentic', 'autonomous', 'workflow', 'automation', 'code',
    'software', 'engineer', 'tech', 'data', 'compute', 'gpu', 'cursor',
}

def is_ai_relevant(text):
    return any(kw in text.lower() for kw in AI_KEYWORDS)

def compute_velocity(t):
    now = datetime.now(timezone.utc)
    created_str = t.get("createdAt", "")
    hours_old = 999.0
    try:
        if created_str:
            try: dt = datetime.strptime(created_str, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            hours_old = (now - dt).total_seconds() / 3600
    except Exception: pass
    likes = t.get("likeCount", 0) or 0
    rts = t.get("retweetCount", 0) or 0
    replies = t.get("replyCount", 0) or 0
    total_eng = likes + rts * 2 + replies * 3
    if hours_old < 1: mult = 10.0
    elif hours_old < 2: mult = 5.0
    elif hours_old < 6: mult = 2.0
    elif hours_old < 24: mult = 1.0
    else: mult = max(0.1, 0.3 * math.exp(-0.02 * (hours_old - 24)))
    reply_ratio = replies / max(likes, 1)
    reply_bonus = min(2.0, 1.0 + reply_ratio * 3)
    return (total_eng / max(hours_old, 0.25)) * mult * reply_bonus, hours_old

def insert_tweet(conn, t, source, topic=""):
    tid = t.get("id", "")
    if not tid: return False
    text = t.get("text", "")
    if not is_ai_relevant(text): return False
    media_url = None
    if t.get("media") and len(t["media"]) > 0:
        media_url = t["media"][0].get("url", "")
    velocity, hours_old = compute_velocity(t)
    author = t.get("author", {})
    try:
        conn.execute("""INSERT OR IGNORE INTO tweets
            (id, text, author_username, author_name, author_id, created_at,
             reply_count, retweet_count, like_count, conversation_id,
             in_reply_to_id, media_url, search_topic, source, velocity_score, hours_old)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tid, text, author.get("username", ""), author.get("name", ""),
             t.get("authorId", ""), t.get("createdAt", ""),
             t.get("replyCount", 0), t.get("retweetCount", 0),
             t.get("likeCount", 0), t.get("conversationId", ""),
             t.get("inReplyToStatusId", ""), media_url, topic, source, velocity, hours_old))
        return True
    except Exception as e:
        log.warning(f"Insert error {tid}: {e}"); return False

def fetch_my_style_tweets(conn, count=40):
    """Fetch YOUR recent tweets - replies/quotes become style examples for scorer"""
    log.info("Fetching your recent tweets for style examples...")
    tweets = run_bird(["user-tweets", YOUR_USERNAME, "-n", str(count)])
    inserted = 0
    for t in tweets:
        tid = t.get("id", "")
        text = t.get("text", "")
        if not tid or text.startswith("RT @"): continue
        likes = t.get("likeCount", 0) or 0
        rts = t.get("retweetCount", 0) or 0
        replies = t.get("replyCount", 0) or 0
        eng = likes + rts * 2 + replies * 3
        is_reply = bool(t.get("inReplyToStatusId")) or text.startswith("@")
        is_quote = bool(t.get("quotedTweet"))
        tweet_type = "quote" if is_quote else ("reply" if is_reply else "original")
        quoted_text = t.get("quotedTweet", {}).get("text", "")[:500] if t.get("quotedTweet") else ""
        try:
            conn.execute("""INSERT OR REPLACE INTO my_style_tweets
                (id, text, tweet_type, like_count, retweet_count, reply_count,
                 engagement, created_at, quoted_tweet_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, text, tweet_type, likes, rts, replies, eng, t.get("createdAt", ""), quoted_text))
            inserted += 1
        except Exception as e:
            log.warning(f"Style insert error {tid}: {e}")
    conn.commit()
    log.info(f"Stored {inserted} style tweets")
    return inserted

def fetch_home(conn, count=20):
    tweets = run_bird(["home", "-n", str(count)])
    inserted = sum(1 for t in tweets if insert_tweet(conn, t, "home", "timeline"))
    conn.commit()
    log.info(f"Home timeline: {inserted} new AI-relevant tweets")
    return inserted

def fetch_search(conn, topic, count=FETCH_PER_TOPIC):
    tweets = run_bird(["search", topic, "-n", str(count)])
    inserted = sum(1 for t in tweets if insert_tweet(conn, t, "search", topic))
    conn.commit()
    log.info(f"Search '{topic}': {inserted} new")
    return inserted

def fetch_mentions(conn, count=15):
    tweets = run_bird(["mentions", "-n", str(count)])
    inserted = 0
    for t in tweets:
        tid = t.get("id", "")
        if not tid: continue
        author = t.get("author", {})
        try:
            conn.execute("""INSERT OR IGNORE INTO mentions
                (id, text, author_username, author_name, author_id, created_at,
                 reply_count, retweet_count, like_count, conversation_id, in_reply_to_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, t.get("text", ""), author.get("username", ""), author.get("name", ""),
                 t.get("authorId", ""), t.get("createdAt", ""),
                 t.get("replyCount", 0), t.get("retweetCount", 0),
                 t.get("likeCount", 0), t.get("conversationId", ""),
                 t.get("inReplyToStatusId", "")))
            inserted += 1
        except Exception: pass
    conn.commit()
    log.info(f"Mentions: {inserted} new")
    return inserted

def cleanup_old(conn, days=3):
    conn.execute("DELETE FROM tweets WHERE status='new' AND score=0 AND fetched_at < datetime('now', ?)", (f'-{days} days',))
    deleted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    if deleted: log.info(f"Cleaned up {deleted} old unscored tweets")

def main():
    if not AUTH_TOKEN or not CT0:
        log.error("X_AUTH_TOKEN and X_CT0 required"); sys.exit(1)
    conn = setup_database()
    total = 0
    topics = load_topics(conn)
    log.info(f'Using {len(topics)} search topics')
    fetch_my_style_tweets(conn, count=40)
    total += fetch_home(conn, count=20)
    for topic in topics:
        total += fetch_search(conn, topic)
    fetch_mentions(conn)
    cleanup_old(conn, days=3)
    new_count = conn.execute("SELECT COUNT(*) FROM tweets WHERE status='new'").fetchone()[0]
    style_count = conn.execute("SELECT COUNT(*) FROM my_style_tweets").fetchone()[0]
    log.info(f"Done! {total} new tweets fetched. {new_count} total new in DB. {style_count} style examples.")
    conn.close()

if __name__ == "__main__":
    main()
