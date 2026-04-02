#!/bin/bash
set -e

# Ensure XDG runtime directory exists
mkdir -p "$XDG_RUNTIME_DIR"

# Start PulseAudio with a null sink for virtual audio
pulseaudio --start --exit-idle-time=-1 || echo "WARN: PulseAudio failed to start — continuing without virtual audio"
pactl load-module module-null-sink sink_name=virtual_speaker sink_properties=device.description="Virtual_Speaker" 2>/dev/null || true
pactl set-default-sink virtual_speaker 2>/dev/null || true

# Start Xvfb in the background (don't use xvfb-run which swallows stdout)
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
sleep 1

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
  echo "ERROR: Xvfb failed to start"
  exit 1
fi

echo "Xvfb started on display :99 (PID $XVFB_PID)"

# Launch node directly so its stdout/stderr go to Docker logs
exec node dist/index.js
