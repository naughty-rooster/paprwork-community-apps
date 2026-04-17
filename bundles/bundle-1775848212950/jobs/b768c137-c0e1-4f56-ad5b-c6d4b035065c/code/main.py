#!/usr/bin/env python3
import argparse, json, logging, os, sqlite3, urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def detect_x_username():
    """Auto-detect X handle via bird whoami."""
    import re, subprocess
    try:
        result = subprocess.run(["bird", "whoami"], capture_output=True, text=True, timeout=15)
        for line in result.stdout.splitlines():
            m = re.search(r"@(\w+)", line)
            if m:
                return m.group(1)
    except Exception as e:
        log.warning(f"bird whoami failed: {e}")
    return os.environ.get("X_USERNAME", "your_handle")

X_USERNAME = detect_x_username()
log = logging.getLogger(__name__)
FEED_JOB_ID = os.environ.get('FEED_JOB_ID', 'a6e3bf40-3d06-44a2-84ca-93ead97a10a9')
DB_PATH = Path(os.path.expanduser(f'~/PAPR/jobs/{FEED_JOB_ID}/data/data.db'))

PAPR_CONTEXT = (
    'Papr.ai = predictive memory layer for AI agents. The PostgreSQL for AI agents. '
    'Use only when the tweet is directly about AI agents, memory, RAG, latency, or agent infra. '
    'Key points: <100ms retrieval, 91% STARK benchmark accuracy, prediction-first memory, unified memory API.'
)
VOICE_RULES = (
    'VOICE RULES:\n'
    '- No hashtags. No emojis unless truly necessary.\n'
    '- Confident, sharp, first-principles.\n'
    '- Under 280 chars for replies, under 240 chars for quotes.\n'
    '- Lead with the insight, not filler.\n'
    '- Prefer a mechanism, distinction, or prediction over agreement.\n'
    '- Mention Papr only when it naturally fits the tweet topic.'
)


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def clean(value, limit=220):
    return ' '.join((value or '').replace('"', "'").split())[:limit]


def search_papr_memory(query: str, api_key: str, max_memories: int = 5) -> list[dict]:
    if not api_key:
        return []
    try:
        req = urllib.request.Request(
            'https://memory.papr.ai/v1/memory/search',
            data=json.dumps({'query': query, 'max_memories': max_memories}).encode(),
            headers={'Content-Type': 'application/json', 'x-api-key': api_key},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            return data.get('data', {}).get('memories', []) or []
    except Exception as e:
        log.warning(f'Papr memory search failed ({query[:36]}): {e}')
        return []


def build_papr_context(api_key: str, topics: list[str]) -> str:
    queries = [
        'my current priorities this week product GTM AI memory agents',
        'my last few days important conversations product strategy positioning',
        'predictive memory differentiation latency accuracy benchmark open source',
        'my frameworks first principles virality PLG developer growth',
        'multi-agent reinforcement learning coordination loss open source win rate',
        'agent collaboration coordination agentic systems',
        f"{' '.join(topics[:5])} my perspective recent context",
    ]
    seen, items = set(), []
    for q in queries:
        for mem in search_papr_memory(q, api_key):
            text = clean(mem.get('content', ''), 420)
            if len(text) < 40 or text in seen:
                continue
            seen.add(text)
            items.append((mem.get('relevance_score', 0), text))
    items.sort(key=lambda x: x[0], reverse=True)
    if not items:
        return ''
    out = '\n'.join(f'- {text}' for _, text in items[:8])
    log.info(f'Loaded {min(8, len(items))} memory snippets')
    return out[:3000]


def load_style_examples(conn) -> str:
    rows = conn.execute("""
        WITH preferred AS (
          SELECT text, tweet_type, like_count, retweet_count, reply_count, engagement, quoted_tweet_text, created_at,
                 CASE tweet_type WHEN 'reply' THEN 3 WHEN 'quote' THEN 2 ELSE 1 END AS type_weight
          FROM my_style_tweets
          WHERE LENGTH(TRIM(text)) > 20
        )
        SELECT * FROM preferred
        ORDER BY type_weight DESC, engagement DESC, datetime(created_at) DESC
        LIMIT 10
    """).fetchall()
    examples = []
    for i, row in enumerate(rows, 1):
        ctx = f" | ref: {clean(row['quoted_tweet_text'], 80)}" if row['quoted_tweet_text'] else ''
        meta = f"[{row['tweet_type']} likes:{row['like_count']} rt:{row['retweet_count']} replies:{row['reply_count']}]"
        examples.append(f"{i}. {clean(row['text'])}\n   {meta}{ctx}")
    return '\n'.join(examples) if examples else VOICE_RULES


def describe_edit(before: str, after: str) -> str:
    notes = []
    if len(after) < len(before):
        notes.append('tighter')
    if '?' in after and '?' not in before:
        notes.append('uses a question')
    if ':' in after and ':' not in before:
        notes.append('stronger framing')
    strong = ['because', 'means', 'actually', 'real', 'leverage', 'constraint', 'distribution', 'memory']
    if sum(word in after.lower() for word in strong) > sum(word in before.lower() for word in strong):
        notes.append('adds mechanism / specificity')
    return ', '.join(notes[:3]) or 'sharper rewrite'


def load_edit_feedback(conn) -> str:
    conn.execute("""CREATE TABLE IF NOT EXISTS draft_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tweet_id TEXT, mode TEXT, original_draft TEXT, edited_draft TEXT,
        was_changed INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')),
        posted_at TEXT, source_tweet_text TEXT, author_username TEXT, score_type TEXT
    )""")
    rows = conn.execute("""
        SELECT mode, original_draft, edited_draft, source_tweet_text, author_username, was_changed, posted_at, created_at
        FROM draft_feedback
        WHERE LENGTH(TRIM(edited_draft)) > 0
        ORDER BY was_changed DESC, datetime(COALESCE(posted_at, created_at)) DESC
        LIMIT 8
    """).fetchall()
    items = []
    for i, row in enumerate(rows, 1):
        before = clean(row['original_draft'], 160)
        after = clean(row['edited_draft'], 160)
        source = clean(row['source_tweet_text'], 90)
        label = f"{row['mode']} to @{row['author_username']}"
        if before and before != after:
            items.append(
                f"{i}. {label} on '{source}'\n"
                f"   before: {before}\n"
                f"   after: {after}\n"
                f"   learned: {describe_edit(before, after)}"
            )
        elif after:
            items.append(f"{i}. {label} on '{source}'\n   kept: {after}")
    return '\n'.join(items)


def build_prompt(tweets, papr_context, style_examples, feedback_examples):
    candidates = [{
        'id': t['id'],
        'author': f"@{t['author_username']}",
        'text': clean(t['text'], 240),
        'likes': t['like_count'],
        'retweets': t['retweet_count'],
        'replies': t['reply_count'],
        'topic': t['search_topic'],
        'velocity': round(t.get('velocity_score', 0), 1),
        'hours_old': round(t.get('hours_old', 999), 1),
    } for t in tweets]
    return f"""
You are choosing the best 10 tweets for @{X_USERNAME} to engage with right now and writing the actual drafts.

Primary goal:
- grow reach by winning early reply slots on high-signal tweets
- sound exactly like the user: sharp, first-principles, mechanism-driven
- use recent memory/context so drafts match what matters this week

What matters now from memory:
{papr_context or '- none available'}

Recent high-performing style examples:
{style_examples}

Feedback loop from the user's own edits. Highest priority: learn from the AFTER versions, not the BEFORE versions:
{feedback_examples or '- no edit feedback yet'}

{VOICE_RULES}

Selection rules:
- pick EXACTLY 10 tweets
- exactly 8 give_value and exactly 2 papr_mention
- papr_mention only if the tweet is specifically about agents, memory, RAG, latency, or agent infra
- prefer tweets where the user can add a mechanism, distinction, prediction, or useful reframing
- avoid generic praise, paraphrasing the tweet, and filler
- if a tweet is a benchmark/result post, explain what the result means or what constraint it reveals
- if edit feedback shows the user tends to tighten, sharpen, or add mechanism, do that

Papr context for the 2 papr_mention slots:
{PAPR_CONTEXT}

Candidates:
{json.dumps(candidates, indent=2)}

Return JSON array only:
[
  {{
    "id": "tweet id",
    "score": 0,
    "score_type": "give_value",
    "score_reason": "one sentence",
    "draft_reply": "<=280 chars",
    "draft_quote": "<=240 chars"
  }}
]
""".strip()


def call_anthropic(prompt: str, api_key: str, max_retries: int = 3):
    import anthropic
    model = 'claude-sonnet-4-20250514'
    log.info(f'Trying Anthropic via SDK: {model} (key prefix: {api_key[:12]}...)')
    client = anthropic.Anthropic(api_key=api_key, max_retries=0)
    for attempt in range(max_retries):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=2200,
                messages=[{'role': 'user', 'content': prompt}],
            )
            text = message.content[0].text.strip()
            if text.startswith('```'):
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
            return json.loads(text.strip())
        except anthropic.RateLimitError:
            wait = min(2 ** attempt * 10, 60)
            log.warning(f'Rate limited, retrying in {wait}s (attempt {attempt+1}/{max_retries})')
            import time; time.sleep(wait)
        except anthropic.APIError as e:
            log.warning(f'Anthropic API error: {e}')
            raise
    raise RuntimeError(f'Anthropic rate limited after {max_retries} retries')


def call_openai(prompt: str, api_key: str):
    payload = {
        'model': 'gpt-5.4',
        'temperature': 0.35,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': 'Return only JSON. The root object must have a key named results containing the array.'},
            {'role': 'user', 'content': prompt},
        ],
    }
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode())
    content = data['choices'][0]['message']['content']
    parsed = json.loads(content)
    return parsed.get('results', parsed)



def call_gemini(prompt: str, api_key: str):
    """Call Gemini 2.0 Flash via REST API."""
    if not api_key:
        raise RuntimeError('No Google API key')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.35,
            'maxOutputTokens': 2400,
            'responseMimeType': 'application/json',
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode())
    text = data['candidates'][0]['content']['parts'][0]['text'].strip()
    if text.startswith('```'):
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())


def heuristic_reply(tweet_text: str, score_type: str):
    text = clean(tweet_text, 220)
    low = text.lower()
    if score_type == 'papr_mention':
        return (
            'The real constraint is memory architecture. Once context keeps growing, search-first retrieval gets slower and noisier. Prediction-first memory is what keeps agent quality compounding instead of collapsing.'[:280],
            'Agent products stop feeling intelligent when memory is bolted on. Memory has to be infra: low-latency, persistent, and improving with use.'[:240],
            'Direct fit for Papr: the thread is about agents/memory and leaves room for a concrete infra angle.'
        )
    if 'benchmark' in low or 'agi' in low or '%' in text:
        return (
            "The interesting part isn't that models miss the benchmark. It's what the failures reveal about planning, search, and state tracking. Benchmarks like this usually get solved by better scaffolding before raw models catch up."[:280],
            'Benchmarks like this are really constraint maps. The gap usually closes when planning + memory + tooling improve, not just the base model.'[:240],
            'Strong benchmark thread where the user can interpret the result instead of paraphrasing it.'
        )
    if 'multi-agent' in low or 'coordination' in low or 'marl' in low or 'reinforcement' in low:
        return (
            'The coordination loss problem is underrated. Most multi-agent systems fail not because individual agents are weak but because decision quality degrades at handoff boundaries. MARL + Monte Carlo closes that gap — agents that learn from each other in context outperform any single-agent loop.'[:280],
            'Multi-agent systems live or die by coordination loss. The teams that solved this with reinforcement learning found something surprising: collaborative decision-making with shared rollouts outperforms even the best single-agent setup in bounded domains.'[:240],
            'Direct match — tweet is about agent coordination/multi-agent systems, the user has first-hand ML work to reference.'
        )
    if 'agent' in low and ('github' in low or 'deploy' in low or 'ship' in low or 'ci' in low or 'devops' in low or 'rsync' in low or 'cloud' in low):
        return (
            "The missing piece isn't removing git — it's agent decision quality at the edge. When you remove PRs and human review, you need a feedback loop that actually catches coordination failures. That's where multi-agent MARL setups earn their place: the system learns from its own deployment errors in real time."[:280],
            "Removing CI/CD rituals only works if agents have a tighter feedback loop underneath. The real constraint is decision coordination, not the toolchain. Autonomous deployment without that is just moving the failure mode downstream."[:240],
            'Tweet is about agents replacing devops; the user can add the coordination/decision quality angle .'
        )
    if 'open source' in low or 'developer' in low or 'tool' in low:
        return (
            'Distribution usually follows developer utility, not announcement volume. The products that win give builders a faster loop, then the ecosystem does the marketing for them.'[:280],
            'Most devtool growth is product first, narrative second. Utility creates usage. Usage creates distribution.'[:240],
            'Good fit for a product/distribution mechanism.'
        )
    return (
        'The leverage is usually in the feedback loop, not the one-shot output. Teams improve faster when each action makes the next one cheaper, sharper, or more informed.'[:280],
        'A lot of this comes down to loop quality. Better loops beat louder opinions.'[:240],
        'General high-signal thread where a concise mechanism-driven angle adds value.'
    )


def fallback_results(tweets):
    results, ai_terms = [], ('ai', 'agent', 'agents', 'memory', 'rag', 'llm', 'context', 'benchmark')
    for i, tweet in enumerate(tweets[:10]):
        joined = ((tweet.get('search_topic') or '') + ' ' + (tweet.get('text') or '')).lower()
        need_papr = len([r for r in results if r['score_type'] == 'papr_mention']) < 2 and any(term in joined for term in ai_terms) and i >= 5
        score_type = 'papr_mention' if need_papr else 'give_value'
        reply, quote, reason = heuristic_reply(tweet.get('text', ''), score_type)
        results.append({
            'id': tweet['id'],
            'score': max(58, 90 - i * 3),
            'score_type': score_type,
            'score_reason': reason,
            'draft_reply': reply,
            'draft_quote': quote,
        })
    return results


def normalize_results(results):
    fixed = []
    for item in results:
        if not item.get('id'):
            continue
        fixed.append({
            'id': str(item.get('id')),
            'score': int(item.get('score', 0) or 0),
            'score_type': 'papr_mention' if item.get('score_type') == 'papr_mention' else 'give_value',
            'score_reason': clean(item.get('score_reason', ''), 220),
            'draft_reply': clean(item.get('draft_reply', ''), 280),
            'draft_quote': clean(item.get('draft_quote', ''), 240),
        })
    fixed = fixed[:10]
    papr = [item for item in fixed if item['score_type'] == 'papr_mention']
    give = [item for item in fixed if item['score_type'] == 'give_value']
    while len(papr) < 2 and give:
        give[-1]['score_type'] = 'papr_mention'
        papr.append(give.pop())
    if len(papr) > 2:
        for item in papr[2:]:
            item['score_type'] = 'give_value'
    return fixed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--anthropic-key', default='')
    parser.add_argument('--openai-key', default='')
    parser.add_argument('--papr-key', default='')
    args = parser.parse_args()

    conn = get_db()
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tweets_score ON tweets(score DESC)")
    rows = conn.execute("""
        SELECT *, (
          velocity_score * 0.45 +
          reply_count * 3 +
          retweet_count * 2 +
          like_count * 0.5 +
          CASE WHEN hours_old < 2 THEN 200 WHEN hours_old < 6 THEN 100 WHEN hours_old < 12 THEN 50 WHEN hours_old < 24 THEN 20 ELSE 0 END
        ) AS composite_prescore
        FROM tweets
        WHERE status='new'
        ORDER BY composite_prescore DESC
        LIMIT 40
    """).fetchall()
    if not rows:
        print(json.dumps({'scored': 0}))
        return
    tweets = [dict(row) for row in rows]
    topics = list({tweet.get('search_topic', '') for tweet in tweets if tweet.get('search_topic')})
    papr_context = build_papr_context(args.papr_key, topics)
    style_examples = load_style_examples(conn)
    feedback_examples = load_edit_feedback(conn)
    prompt = build_prompt(tweets, papr_context, style_examples, feedback_examples)

    results = None
    if args.anthropic_key:
        try:
            results = call_anthropic(prompt, args.anthropic_key)
            log.info('Scoring/drafting succeeded via Anthropic claude-sonnet-4-20250514')
        except Exception as e:
            log.warning(f'Anthropic claude-sonnet-4-20250514 failed: {e}')
    if results is None and args.openai_key:
        try:
            results = call_openai(prompt, args.openai_key)
            log.info('Scoring/drafting succeeded via OpenAI fallback')
        except Exception as e:
            log.warning(f'OpenAI fallback failed: {e}')
    if results is None:
        log.warning('All LLM paths failed, using heuristic fallback')
        results = fallback_results(tweets)

    results = results if isinstance(results, list) else results.get('results', [])
    results = normalize_results(results)
    for result in results:
        username = next((tweet['author_username'] for tweet in tweets if tweet['id'] == result['id']), '')
        conn.execute("""
            UPDATE tweets SET
              score=?, score_type=?, score_reason=?, draft_reply=?, draft_quote=?,
              author_profile_image=?, papr_context=?, scored_at=datetime('now')
            WHERE id=?
        """, (
            result['score'], result['score_type'], result['score_reason'], result['draft_reply'], result['draft_quote'],
            f'https://unavatar.io/twitter/{username}',
            papr_context if result['score_type'] == 'papr_mention' else '',
            result['id'],
        ))
    conn.commit()
    conn.close()
    print(json.dumps({'scored': len(results), 'candidates': len(tweets)}))


if __name__ == '__main__':
    main()
