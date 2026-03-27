#!/usr/bin/env python3
"""Generate a macOS-style landscape background themed around today's meetings."""
import base64
import datetime as dt
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data'
IMG_DIR = DATA_DIR / 'backgrounds'
IMG_DIR.mkdir(parents=True, exist_ok=True)

def log(*parts):
    print(*parts, flush=True)

def find_meetings_db():
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

def connect(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con

def ensure_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS location_background (
      id TEXT PRIMARY KEY, city TEXT DEFAULT '', reason TEXT DEFAULT '',
      prompt TEXT DEFAULT '', image_path TEXT DEFAULT '', image_url TEXT DEFAULT '',
      image_data TEXT DEFAULT '', generated_on TEXT DEFAULT '',
      source_events_json TEXT DEFAULT '[]',
      updated_at INTEGER DEFAULT (strftime('%s','now'))
    );
    ''')
    try:
        con.execute("ALTER TABLE location_background ADD COLUMN image_data TEXT DEFAULT ''")
    except Exception:
        pass
    con.commit()

# macOS-style landscape scenes mapped to meeting themes
SCENE_MAP = {
    'sales':       'dramatic coastal cliffs with crashing waves at golden hour, like Big Sur',
    'demo':        'crystal clear alpine lake reflecting snow-capped peaks under blue sky',
    'engineering': 'vast desert canyon with layered red rock formations at sunset',
    'product':     'rolling green hills with wildflowers under soft morning light, like Sonoma',
    'design':      'serene Japanese garden with cherry blossoms and still pond reflections',
    'partner':     'two mountain peaks side by side with golden clouds between them',
    'investor':    'aerial view of clouds from above at sunrise, rose gold and amber light',
    'standup':     'misty forest with sunbeams breaking through tall redwood trees',
    'daily':       'calm ocean horizon at blue hour with soft peach-to-indigo gradient sky',
    'strategy':    'winding mountain road through dramatic peaks disappearing into distance',
    'interview':   'open meadow with a single oak tree under warm afternoon light',
    'onboarding':  'dawn breaking over a mountain range with pink and gold clouds',
    'review':      'still lake at twilight perfectly reflecting a purple mountain skyline',
    'brainstorm':  'dramatic thunderstorm clouds with rays of sun breaking through',
    'workshop':    'terraced rice fields with morning mist in lush green valley',
    'leadership':  'lone lighthouse on rocky coast with dramatic sky and ocean spray',
    'finance':     'geometric sand dune ridgelines in warm amber light, like Sahara',
    'launch':      'rocket trail across a deep blue twilight sky over desert landscape',
    'mentor':      'ancient forest path with dappled sunlight through cathedral-like canopy',
    'cxo':         'sweeping vista from mountain summit overlooking clouds and valleys below',
    'forum':       'vast savanna at golden hour with acacia trees silhouetted against sky',
    'sync':        'parallel rows of lavender fields stretching to distant purple mountains',
    'pitch':       'dramatic Yosemite-style granite cliff face with waterfall in golden light',
    'retro':       'layered mountain ridges fading into atmospheric haze at blue hour',
}

DEFAULT_SCENE = 'sweeping mountain landscape with rolling clouds at golden hour'

def extract_scene(titles):
    scenes = []
    for title in titles:
        t = title.lower()
        for keyword, scene in SCENE_MAP.items():
            if keyword in t:
                scenes.append(scene)
                break
    if not scenes:
        scenes = [DEFAULT_SCENE]
    # Deduplicate, keep first 2
    seen = set()
    unique = []
    for s in scenes:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:2]

def build_prompt(scenes):
    scene_desc = scenes[0] if len(scenes) == 1 else f"{scenes[0]}, blending into {scenes[1]}"

    return (
        f"A breathtaking wide landscape photograph: {scene_desc}. "
        f"Shot on Hasselblad medium format, 65mm f/4 lens. "
        f"Photorealistic, cinematic, 16:9 aspect ratio. "
        f"Rich natural colors — deep blues, warm golds, soft greens, earthy tones. "
        f"Dramatic natural lighting with volumetric god rays and atmospheric haze. "
        f"Style of macOS desktop wallpaper — Sonoma, Sequoia, Big Sur. "
        f"Ultra high quality, sharp foreground detail with soft atmospheric distance. "
        f"Vivid but not oversaturated. Majestic, calm, awe-inspiring. "
        f"No text, no people, no buildings, no UI elements, no logos, no words."
    )

def get_todays_meetings(con):
    now = dt.datetime.now()
    rows = con.execute(
        "SELECT title FROM calendar_events WHERE start_time >= ? AND start_time <= ? ORDER BY start_time ASC",
        (now.strftime('%Y-%m-%dT00:00'), now.strftime('%Y-%m-%dT23:59')),
    ).fetchall()
    return [r['title'] for r in rows if r['title']]

def generate_image(api_key, prompt):
    try:
        return _generate_nano_banana(api_key, prompt)
    except Exception as e:
        log(f"Nano Banana 2.5 failed: {e}, falling back to Imagen 4.0")
    return _generate_imagen(api_key, prompt)

def _generate_nano_banana(api_key, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    for part in data.get('candidates', [{}])[0].get('content', {}).get('parts', []):
        ib = part.get('inlineData', {})
        if ib.get('data'):
            log("Generated with Nano Banana 2.5")
            raw = base64.b64decode(ib['data'])
            mime = 'image/png' if raw[:4] == b'\x89PNG' else 'image/jpeg'
            return f"data:{mime};base64,{ib['data']}"
    raise RuntimeError("No image in Nano Banana response")

def _generate_imagen(api_key, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:generateImages?key={api_key}"
    body = json.dumps({
        "prompt": prompt,
        "config": {"numberOfImages": 1, "outputOptions": {"mimeType": "image/jpeg"}},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    for img in data.get('generatedImages', []):
        b64 = img.get('image', {}).get('imageBytes', '')
        if b64:
            log("Generated with Imagen 4.0")
            return f"data:image/jpeg;base64,{b64}"
    raise RuntimeError("No image in Imagen response")

def main():
    api_key = os.environ.get('GOOGLE_API_KEY', '')
    if not api_key:
        log("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    meetings_db = find_meetings_db()
    log(f"Meetings DB: {meetings_db}")
    mcon = connect(meetings_db)
    titles = get_todays_meetings(mcon)
    log(f"Today's meetings ({len(titles)}): {titles[:6]}")
    mcon.close()

    scenes = extract_scene(titles)
    prompt = build_prompt(scenes)
    log(f"Prompt: {prompt[:200]}...")

    img_data_uri = generate_image(api_key, prompt)
    log(f"Image size: {len(img_data_uri) // 1024}KB")

    # Save to meetings DB
    con = connect(meetings_db)
    ensure_schema(con)
    today = dt.date.today().isoformat()
    con.execute(
        "INSERT OR REPLACE INTO location_background (id, prompt, image_data, generated_on, source_events_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, strftime('%s','now'))",
        ('current', prompt, img_data_uri, today, json.dumps(titles[:6])),
    )
    con.commit()
    con.close()
    log(f"Saved to DB (id=current, generated_on={today})")

import sys
if __name__ == '__main__':
    main()
