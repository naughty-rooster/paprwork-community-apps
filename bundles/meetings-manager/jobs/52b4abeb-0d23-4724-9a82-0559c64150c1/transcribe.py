import os
import sqlite3
import json
import subprocess
import tempfile
from pathlib import Path
from openai import OpenAI

# Paths
RECORDER_JOB_DIR = os.path.expanduser("~/PAPR/jobs/54837f40-1e64-4810-a387-f81151d014af")

def find_meetings_db():
    for root, _, files in os.walk(os.path.expanduser("~/PAPR/jobs")):
        if root.endswith("/data") and "data.db" in files:
            db_path = os.path.join(root, "data.db")
            try:
                conn = sqlite3.connect(db_path)
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                conn.close()
                if "meetings" in tables:
                    return db_path
            except Exception:
                pass
    raise RuntimeError("Could not find meetings database")

MEETINGS_DB = find_meetings_db()
AUDIO_FILE = os.path.join(RECORDER_JOB_DIR, "data", "recording.wav")
MAX_WHISPER_SIZE = 24 * 1024 * 1024  # 24MB to stay under 25MB limit

def get_current_meeting_id():
    """Read the current meeting ID from the recorder's state file"""
    state_file = os.path.join(RECORDER_JOB_DIR, "data", "current_meeting.txt")
    if os.path.exists(state_file):
        return open(state_file).read().strip()
    return None

def compress_if_needed(audio_path):
    """Compress WAV to MP3 if file exceeds Whisper's 25MB limit"""
    file_size = os.path.getsize(audio_path)
    if file_size <= MAX_WHISPER_SIZE:
        return audio_path, False
    
    print(f"File too large ({file_size // (1024*1024)}MB > 24MB), compressing to MP3...")
    mp3_path = audio_path.replace(".wav", "_compressed.mp3")
    
    # Adaptive bitrate based on file size to target ~15MB output
    if file_size > 400 * 1024 * 1024:
        bitrate = "12k"
    elif file_size > 200 * 1024 * 1024:
        bitrate = "16k"
    elif file_size > 100 * 1024 * 1024:
        bitrate = "24k"
    elif file_size > 50 * 1024 * 1024:
        bitrate = "48k"
    else:
        bitrate = "64k"
    
    print(f"Using {bitrate} bitrate for {file_size // (1024*1024)}MB file")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", bitrate, mp3_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}")
        raise RuntimeError("Failed to compress audio")
    
    new_size = os.path.getsize(mp3_path)
    print(f"Compressed: {file_size // (1024*1024)}MB -> {new_size // (1024*1024)}MB")
    
    # If still too large, retry with progressively lower bitrate
    for retry_br in ["16k", "12k", "8k"]:
        if new_size <= MAX_WHISPER_SIZE:
            break
        print(f"Still too large ({new_size // (1024*1024)}MB), retrying with {retry_br}...")
        os.remove(mp3_path)
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", retry_br, mp3_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError("Failed to compress audio on retry")
        new_size = os.path.getsize(mp3_path)
        print(f"Retry ({retry_br}): {file_size // (1024*1024)}MB -> {new_size // (1024*1024)}MB")
    
    return mp3_path, True

def get_openai_client():
    """Try OPENAI_PLATFORM_KEY first, then OPENAI_API_KEY"""
    platform_key = os.environ.get("OPENAI_PLATFORM_KEY", "")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    key = platform_key if platform_key else api_key
    if not key:
        raise RuntimeError("No OpenAI API key found. Set OPENAI_PLATFORM_KEY or OPENAI_API_KEY.")
    return OpenAI(api_key=key)

def transcribe_audio(audio_path):
    """Send audio to Whisper API for transcription, compressing if needed"""
    client = get_openai_client()
    
    upload_path, was_compressed = compress_if_needed(audio_path)
    file_size = os.path.getsize(upload_path)
    print(f"Transcribing audio file: {upload_path} ({file_size} bytes)")
    
    try:
        with open(upload_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )
    finally:
        if was_compressed and os.path.exists(upload_path):
            os.remove(upload_path)
    
    return transcript

def save_transcript(meeting_id, transcript):
    """Save transcript to meetings database"""
    conn = sqlite3.connect(MEETINGS_DB)
    
    # Build full text
    full_text = transcript.text
    
    # Build segments JSON for detailed view
    segments = []
    if hasattr(transcript, 'segments') and transcript.segments:
        for seg in transcript.segments:
            segments.append({
                "start": seg.start if hasattr(seg, 'start') else seg.get('start', 0),
                "end": seg.end if hasattr(seg, 'end') else seg.get('end', 0),
                "text": seg.text if hasattr(seg, 'text') else seg.get('text', '')
            })
    
    duration = 0
    if segments:
        duration = int(segments[-1]["end"])
    
    conn.execute("""
        UPDATE meetings 
        SET transcript = ?, 
            duration = ?,
            status = 'pending',
            updated_at = strftime('%s','now')
        WHERE id = ?
    """, (full_text, duration, meeting_id))
    
    conn.commit()
    conn.close()
    
    print(f"Transcript saved: {len(full_text)} chars, {duration}s duration")
    print(f"Meeting {meeting_id} status -> pending (ready for summarizer)")
    return full_text

def process_meeting(meeting_id, audio_path):
    """Process a single meeting: transcribe and save"""
    if not os.path.exists(audio_path):
        print(f"  SKIP: No audio file at {audio_path}")
        return False
    
    file_size = os.path.getsize(audio_path)
    if file_size < 1000:
        print(f"  SKIP: Audio file too small ({file_size} bytes)")
        return False
    
    # Mark as transcribing
    conn = sqlite3.connect(MEETINGS_DB)
    conn.execute("UPDATE meetings SET status='transcribing', updated_at=strftime('%s','now') WHERE id=?", (meeting_id,))
    conn.commit()
    conn.close()
    print(f"  Status -> transcribing")
    
    # Transcribe
    transcript = transcribe_audio(audio_path)
    
    # Save
    text = save_transcript(meeting_id, transcript)
    preview = text[:300] + "..." if len(text) > 300 else text
    print(f"  Preview: {preview}\n")
    return True

def main():
    # First, process the current meeting from recorder (latest recording)
    current_id = get_current_meeting_id()
    
    # Get all meetings that need transcription
    conn = sqlite3.connect(MEETINGS_DB)
    rows = conn.execute(
        "SELECT id, title, audio_path FROM meetings WHERE status IN ('recorded','transcribing') ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    
    if not rows:
        print("No meetings to transcribe.")
        return
    
    print(f"Found {len(rows)} meeting(s) to transcribe.\n")
    success_count = 0
    
    for mid, title, audio_path in rows:
        print(f"Processing: {title} ({mid})")
        
        # Use stored audio_path, fall back to per-meeting file, then current recording
        per_meeting_path = os.path.join(RECORDER_JOB_DIR, "data", "recordings", f"{mid}.wav")
        if audio_path and os.path.exists(audio_path):
            path = audio_path
        elif os.path.exists(per_meeting_path):
            path = per_meeting_path
        elif mid == current_id:
            path = AUDIO_FILE
        else:
            print(f"  SKIP: No audio file found (audio_path={audio_path})")
            continue
        
        try:
            if process_meeting(mid, path):
                success_count += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            # Reset status back to recorded so it can retry
            c = sqlite3.connect(MEETINGS_DB)
            c.execute("UPDATE meetings SET status='recorded', updated_at=strftime('%s','now') WHERE id=?", (mid,))
            c.commit()
            c.close()
    
    print(f"\nDone! Transcribed {success_count}/{len(rows)} meetings.")

if __name__ == "__main__":
    main()
