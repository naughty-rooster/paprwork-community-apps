#!/bin/bash
RECORDER_DIR=/Users/amirkabbara/PAPR/jobs/54837f40-1e64-4810-a387-f81151d014af
touch "$RECORDER_DIR/data/stop_signal"
echo "Stop signal sent"
# Wait up to 10s for recorder to stop
for i in $(seq 1 10); do
  if ! pgrep -f './recorder.*\.wav' > /dev/null 2>&1; then
    echo "Recorder stopped after ${i}s"
    exit 0
  fi
  sleep 1
done
# Force kill if still running
echo "Recorder didn't stop gracefully, force killing..."
pkill -f './recorder.*\.wav' 2>/dev/null || true
sleep 1
echo "Done"
