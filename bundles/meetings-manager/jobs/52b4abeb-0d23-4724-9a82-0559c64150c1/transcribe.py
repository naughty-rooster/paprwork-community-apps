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
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", "64k", mp3_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}")
        raise RuntimeError("Failed to compress audio")
    
    new_size = os.path.getsize(mp3_path)
    print(f"Compressed: {file_size // (1024*1024)}MB -> {new_size // (1024*1024)}MB")
    return mp3_path, True

def transcribe_audio(audio_path):
    """Send audio to Whisper API for transcription, compressing if needed"""
    client = OpenAI()
    
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

def main():
    # Check audio file exists
    if not os.path.exists(AUDIO_FILE):
        print(f"ERROR: No audio file at {AUDIO_FILE}")
        return
    
    file_size = os.path.getsize(AUDIO_FILE)
    if file_size < 1000:
        print(f"ERROR: Audio file too small ({file_size} bytes) - recording may have failed")
        return
    
    # Get meeting ID
    meeting_id = get_current_meeting_id()
    if not meeting_id:
        print("ERROR: No current meeting ID found")
        return
    
    print(f"Processing meeting: {meeting_id}")
    
    # Mark as transcribing so the UI shows progress
    conn = sqlite3.connect(MEETINGS_DB)
    conn.execute("UPDATE meetings SET status='transcribing', updated_at=strftime('%s','now') WHERE id=?", (meeting_id,))
    conn.commit()
    conn.close()
    print(f"Meeting {meeting_id} status -> transcribing")
    
    # Transcribe
    transcript = transcribe_audio(AUDIO_FILE)
    
    # Save
    text = save_transcript(meeting_id, transcript)
    
    # Preview
    preview = text[:500] + "..." if len(text) > 500 else text
    print(f"\nTranscript preview:\n{preview}")
    print("\nDone! Summarizer can now process this meeting.")

if __name__ == "__main__":
    main()
