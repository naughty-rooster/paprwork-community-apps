#!/usr/bin/env python3
import base64
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data'
IMG_DIR = DATA_DIR / 'backgrounds'
IMG_DIR.mkdir(parents=True, exist_ok=True)

def log(*parts):
    print(*parts, flush=True)

def find_meetings_db() -> Path:
    for db in Path.home().glob('PAPR/jobs/*/data/data.db'):
        try:
            con = sqlite3.connect(db)
            ok = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calendar_events'").fetchone()
            con.close()
            if ok:
                return db
        except Exception:
            pass
    raise RuntimeError('meetings DB not found')

def connect(db: Path):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con

def ensure_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS location_override (
      id TEXT PRIMARY KEY,
      city TEXT DEFAULT '',
      lat REAL DEFAULT 0,
      lon REAL DEFAULT 0,
      source TEXT DEFAULT '',
      updated_at INTEGER DEFAULT (strftime('%s','now'))
    );
    CREATE TABLE IF NOT EXISTS location_background (
      id TEXT PRIMARY KEY,
      city TEXT DEFAULT '',
      reason TEXT DEFAULT '',
      prompt TEXT DEFAULT '',
      image_path TEXT DEFAULT '',
      image_url TEXT DEFAULT '',
      image_data TEXT DEFAULT '',
      generated_on TEXT DEFAULT '',
      source_events_json TEXT DEFAULT '[]',
      updated_at INTEGER DEFAULT (strftime('%s','now'))
    );
    CREATE TABLE IF NOT EXISTS background_preferences (
      id TEXT PRIMARY KEY,
      visual_style TEXT DEFAULT '',
      personal_context TEXT DEFAULT '',
      preferred_home_city TEXT DEFAULT 'San Francisco',
      updated_at INTEGER DEFAULT (strftime('%s','now'))
    );
    ''')
    # Migrate: add image_data column if missing (for existing installs)
    try:
        con.execute("ALTER TABLE location_background ADD COLUMN image_data TEXT DEFAULT ''")
    except Exception:
        pass  # column already exists
    row = con.execute("SELECT id FROM background_preferences WHERE id='default'").fetchone()
    if not row:
        con.execute(
            "INSERT INTO background_preferences (id, visual_style, personal_context, preferred_home_city) VALUES ('default', ?, ?, ?)",
            (
                'simple, beautiful, photorealistic, cinematic, elegant, calm, uncluttered, premium editorial, liquid-glass friendly negative space',
                'Subtle sense of ambition, warmth, and focus. Good for a meetings workspace. Inspired by clean Apple-like taste. No text or logos.',
                'San Francisco',
            ),
        )
    con.commit()

def load_prefs(con):
    row = con.execute("SELECT * FROM background_preferences WHERE id='default'").fetchone()
    return dict(row) if row else {}

CITY_PATTERNS = {
    'New York': [r'\bnew york\b', r'\bnyc\b', r'\bmanhattan\b', r'\bbrooklyn\b', r'\bqueens\b', r'\bbronx\b', r'\bstaten island\b'],
    'San Francisco': [r'\bsan francisco\b', r'\bsf\b', r'\bsoho house sf\b', r'\bmission district\b', r'\bsoma\b', r'\bmarin\b', r'\boakland\b', r'\bberkeley\b', r'\bpleasanton\b', r'\bdublin, ca\b', r'\bsan ramon\b'],
}

CITY_SCENES = {
    'New York': 'Lower Manhattan and Midtown mood, elegant skyline layers, warm dusk light reflecting on glass, understated luxury, realistic atmosphere',
    'San Francisco': 'San Francisco hills and bay atmosphere, soft marine fog, golden early morning or blue hour light, refined realistic editorial photography',
}

BUSINESS_CALENDARS = {'Calendar', 'Work', 'Meetings'}

def detect_city(text: str):
    t = text.lower()
    for city, patterns in CITY_PATTERNS.items():
        for p in patterns:
            if re.search(p, t):
                return city
    return None

def score_event(row, now):
    text = ' '.join([row['title'] or '', row['location'] or '', row['calendar_name'] or ''])
    city = detect_city(text)
    if not city:
        return None
    try:
        start = dt.datetime.fromisoformat((row['start_time'] or '').replace('Z', '+00:00'))
    except Exception:
        start = now
    day_delta = abs((start.date() - now.date()).days)
    duration_hours = 1.0
    try:
        end = dt.datetime.fromisoformat((row['end_time'] or '').replace('Z', '+00:00'))
        duration_hours = max(0.5, (end - start).total_seconds() / 3600.0)
    except Exception:
        end = start
    current_bonus = 10.0 if start <= now <= end else 0.0
    next_bonus = 4.0 if 0 <= (start - now).total_seconds() <= 6 * 3600 else 0.0
    day_weight = max(0.5, 3.5 - day_delta)
    cal_name = (row['calendar_name'] or '').strip()
    cal_weight = 3.0 if cal_name in BUSINESS_CALENDARS else 1.0
    loc_weight = 3.0 if row['location'] and 'http' not in row['location'].lower() else 0.5
    duration_weight = min(2.5, duration_hours * 0.6)
    title_bonus = 1.5 if any(k in (row['title'] or '').lower() for k in ['mentor', 'office', 'meeting', 'partner', 'papr']) else 0.0
    score = day_weight + cal_weight + loc_weight + duration_weight + title_bonus + current_bonus + next_bonus
    return city, score

def infer_city(con, prefs):
    now = dt.datetime.now()
    override = con.execute("SELECT city, source, updated_at FROM location_override WHERE id='latest' LIMIT 1").fetchone()
    if override and override['city']:
        age_hours = (now.timestamp() - float(override['updated_at'] or 0)) / 3600
        if age_hours <= 36:
            city = override['city']
            reason = f"Live location says {city}"
            if override['source']:
                reason += f" — via {override['source']}"
            return city, reason, [{'city': city, 'score': 100.0, 'title': 'live-location', 'start_time': now.isoformat(), 'location': city, 'calendar_name': override['source'] or 'geolocation'}]
    rows = con.execute(
        "SELECT title, start_time, end_time, location, calendar_name FROM calendar_events WHERE start_time >= ? AND start_time <= ? ORDER BY start_time ASC",
        ((now - dt.timedelta(days=1)).strftime('%Y-%m-%dT00:00'), (now + dt.timedelta(days=4)).strftime('%Y-%m-%dT23:59')),
    ).fetchall()
    scores = {}
    evidence = []
    for row in rows:
        scored = score_event(row, now)
        if not scored:
            continue
        city, score = scored
        scores[city] = scores.get(city, 0.0) + score
        evidence.append({
            'city': city,
            'score': round(score, 2),
            'title': row['title'],
            'start_time': row['start_time'],
            'location': row['location'],
            'calendar_name': row['calendar_name'],
        })
    if scores:
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        city = ranked[0][0]
        source = [e for e in evidence if e['city'] == city][:8]
        seen_titles = []
        for e in source:
            title = e.get('title')
            if title and title not in seen_titles:
                seen_titles.append(title)
        top_titles = ', '.join(seen_titles[:2])
        backup = ranked[1][0] if len(ranked) > 1 else None
        reason = f"Calendar says {city} right now"
        if top_titles:
            reason += f" — driven by {top_titles}"
        if backup and scores[backup] >= max(6.0, scores[city] * 0.35):
            reason += f", then likely shifts toward {backup} next"
        return city, reason, source
    city = prefs.get('preferred_home_city') or 'San Francisco'
    return city, f"No clear city found in calendar; fell back to preferred home city: {city}", []

def infer_personal_context(con, city):
    now = dt.datetime.now()
    rows = con.execute(
        "SELECT title, calendar_name, start_time, location FROM calendar_events WHERE start_time >= ? AND start_time <= ? ORDER BY start_time ASC LIMIT 20",
        ((now - dt.timedelta(days=1)).strftime('%Y-%m-%dT00:00'), (now + dt.timedelta(days=5)).strftime('%Y-%m-%dT23:59')),
    ).fetchall()
    family_titles, work_titles = [], []
    for row in rows:
        title = (row['title'] or '').strip()
        cal = (row['calendar_name'] or '').strip().lower()
        text = ' '.join([title, row['location'] or '', row['calendar_name'] or ''])
        detected = detect_city(text)
        if detected and detected != city:
            continue
        if 'family' in cal and title:
            family_titles.append(title)
        elif title:
            work_titles.append(title)
    family_titles = family_titles[:3]
    work_titles = work_titles[:3]
    family_note = 'A subtle sense of family warmth and being grounded by the people who matter most.' if family_titles else ''
    work_note = f"Professional context includes: {', '.join(work_titles)}." if work_titles else ''
    return ' '.join([family_note, work_note]).strip()


def build_prompt(city, prefs, personal_context):
    style = prefs.get('visual_style') or 'simple, beautiful, photorealistic, cinematic, elegant'
    context = prefs.get('personal_context') or 'Calm focus and warmth. No text.'
    merged_context = ' '.join([context, personal_context]).strip()
    city_scene = CITY_SCENES.get(city, f'{city} atmosphere, realistic city photography, tasteful and minimal')
    return (
        f"Create a wide premium background image for a meetings app. "
        f"City: {city}. Scene: {city_scene}. "
        f"Style: {style}. Context: {merged_context}. "
        f"Make it feel beautiful, simple, realistic, and emotionally intelligent. "
        f"Composition should be clean and minimal with generous negative space for glass UI overlays, softly layered depth, realistic lighting, premium editorial photography, no people in the foreground, no text, no logos, no watermarks. "
        f"The image should quietly reflect the user's current city, ambitions, and personal warmth without becoming busy or literal."
    )

def _extract_image(data):
    for cand in data.get('candidates', []):
        for part in cand.get('content', {}).get('parts', []):
            inline = part.get('inlineData') or {}
            if inline.get('data'):
                return base64.b64decode(inline['data'])
    return None

def call_gemini(prompt):
    key = os.environ.get('GOOGLE_API_KEY', '').strip()
    if not key:
        log("GOOGLE_API_KEY not set — skipping background generation (will use default gradient)")
        return None
    models = [
        'nano-banana-pro-preview',
        'gemini-3.1-flash-image-preview',
        'gemini-2.5-flash-image',
        'gemini-3-pro-image-preview',
        'gemini-2.0-flash-001',
    ]
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'responseModalities': ['TEXT', 'IMAGE']},
    }
    last_err = ''
    for model in models:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode())
            img = _extract_image(data)
            if img:
                log('Model used:', model)
                return img
            last_err = f'No image returned from {model}: {json.dumps(data)[:400]}'
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            last_err = f'Gemini API error for {model} ({e.code}): {body[:500]}'
            if e.code in (400, 401, 403):
                break
    raise RuntimeError(last_err or 'Gemini image generation failed')

def save_row(con, city, reason, prompt, image_path, generated_on, source):
    image_url = f'file://{image_path}' if image_path else ''
    # Build base64 data URL from image file for direct embedding in app
    image_data = ''
    if image_path and Path(str(image_path)).exists():
        raw = Path(str(image_path)).read_bytes()
        image_data = f'data:image/png;base64,{base64.b64encode(raw).decode()}'
    con.execute(
        '''INSERT INTO location_background (id, city, reason, prompt, image_path, image_url, image_data, generated_on, source_events_json, updated_at)
           VALUES ('daily', ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
           ON CONFLICT(id) DO UPDATE SET city=excluded.city, reason=excluded.reason, prompt=excluded.prompt,
           image_path=excluded.image_path, image_url=excluded.image_url, image_data=excluded.image_data, generated_on=excluded.generated_on,
           source_events_json=excluded.source_events_json, updated_at=strftime('%s','now')''',
        (city, reason, prompt, str(image_path), image_url, image_data, generated_on, json.dumps(source)),
    )
    con.commit()

def main():
    force = '--force' in sys.argv
    db = find_meetings_db()
    log('Using DB:', db)
    con = connect(db)
    ensure_schema(con)
    prefs = load_prefs(con)
    city, reason, source = infer_city(con, prefs)
    personal_context = infer_personal_context(con, city)
    prompt = build_prompt(city, prefs, personal_context)
    today = dt.date.today().isoformat()
    existing = con.execute("SELECT city, generated_on, image_path FROM location_background WHERE id='daily'").fetchone()
    if existing and not force and existing['city'] == city and existing['generated_on'] == today and existing['image_path']:
        log('SKIP: background already generated today for', city)
        save_row(con, city, reason, prompt, existing['image_path'], today, source)
        return
    save_row(con, city, reason, prompt, (existing['image_path'] if existing and existing['image_path'] else ''), today, source)
    img = call_gemini(prompt)
    if img is None:
        log("No image generated (missing API key). App will use gradient fallback.")
        return
    safe = city.lower().replace(' ', '-')
    out_path = IMG_DIR / f'{safe}-{today}.png'
    out_path.write_bytes(img)
    save_row(con, city, reason, prompt, out_path, today, source)
    log('SUCCESS:', city, out_path, len(img), 'bytes')

if __name__ == '__main__':
    main()
