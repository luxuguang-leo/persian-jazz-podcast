#!/bin/bash
# ============================================================
# YouTube Channel Download — Persian Jazz Sources
# Downloads new videos from We Are Jazz and QajarJazz channels
# 
# Prerequisites:
#   Run ~/Downloads/update_ytdlp.sh first to install yt-dlp-new
#   Requires Trojan-Qt5 proxy (HTTP 127.0.0.1:58591)
# ============================================================

set -e

PROXY="http://127.0.0.1:7897"
YT="/Users/luxuguang/miniconda3/bin/yt-dlp"

WAJ_DIR="$HOME/Downloads/WeAreJazz"
QJJ_DIR="$HOME/Downloads/QajarJazz/QajarJazz"
mkdir -p "$WAJ_DIR" "$QJJ_DIR"

echo "=== We Are Jazz Channel ==="
"$YT" --proxy "$PROXY" \
  --download-archive /tmp/waj_archive.txt \
  -o "$WAJ_DIR/%(title)s.%(ext)s" \
  -f "bestaudio[ext=m4a]/bestaudio" \
  --no-overwrites \
  --ignore-errors \
  "https://www.youtube.com/@WeAreJazz/videos"

echo ""
echo "=== QajarJazz Channel ==="
"$YT" --proxy "$PROXY" \
  --download-archive /tmp/qjj_archive.txt \
  -o "$QJJ_DIR/%(title)s.%(ext)s" \
  -f "bestaudio[ext=m4a]/bestaudio" \
  --no-overwrites \
  --ignore-errors \
  "https://www.youtube.com/@QajarJazz/videos"

echo ""
echo "=== Done ==="
echo "WeAreJazz: $(ls "$WAJ_DIR"/*.m4a 2>/dev/null | wc -l) files"
echo "QajarJazz: $(ls "$QJJ_DIR"/*.m4a 2>/dev/null | wc -l) files"