#!/bin/bash
# Persian Jazz Podcast: Download → Scan → Upload pipeline
# Run weekly via launchd or manually: bash ~/Downloads/pipeline.sh
set -e
cd ~/Downloads

echo "=== Step 1/3: Download new videos ==="
YT="/usr/local/bin/yt-dlp"
"$YT" --proxy http://127.0.0.1:58591 \
  --download-archive /tmp/waj_archive.txt \
  -o "$HOME/Downloads/WeAreJazz/%(title)s.%(ext)s" \
  -f "bestaudio[ext=m4a]/bestaudio" \
  --no-overwrites --ignore-errors \
  "https://www.youtube.com/@WeAreJazz/videos" 2>&1 | grep -v "^$"

"$YT" --proxy http://127.0.0.1:58591 \
  --download-archive /tmp/qjj_archive.txt \
  -o "$HOME/Downloads/QajarJazz/QajarJazz/%(title)s.%(ext)s" \
  -f "bestaudio[ext=m4a]/bestaudio" \
  --no-overwrites --ignore-errors \
  "https://www.youtube.com/@QajarJazz/videos" 2>&1 | grep -v "^$"

echo "=== Step 2/3: Scan new files ==="
python3 ~/Downloads/scan_new.py

echo "=== Step 3/3: Upload + RSS update ==="
export GITHUB_TOKEN=$(grep GITHUB_TOKEN ~/.hermes/.env | cut -d= -f2-)
python3 ~/Downloads/weekly_upload.py

echo "=== Pipeline complete ==="
