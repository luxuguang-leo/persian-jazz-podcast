#!/bin/bash
# Push feed.xml with show notes to GitHub Pages.
# Run from user's Mac (needs proxy for GitHub API access).
set -e
cd /tmp
GITHUB_TOKEN=$(grep GITHUB_TOKEN ~/.hermes/.env | cut -d= -f2-)
FEED_PATH="/Users/leo/Library/Mobile Documents/iCloud~md~obsidian/Documents/001-项目/波斯爵士播客/feed.xml"

echo "Getting current SHA..."
SHA=$(curl -s --max-time 30 \
  -H "Authorization: token $GITHUB_TOKEN" \
  --proxy http://127.0.0.1:58591 \
  "https://api.github.com/repos/luxuguang-leo/persian-jazz-podcast/contents/feed.xml" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null)
echo "SHA: $SHA"

python3 << PYEOF
import json, base64
payload = {
    "message": "Update feed with show notes",
    "sha": "$SHA",
    "content": base64.b64encode(open("$FEED_PATH", "rb").read()).decode()
}
with open("/tmp/payload.json", "w") as f:
    json.dump(payload, f)
PYEOF

curl -s --max-time 60 -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/payload.json \
  --proxy http://127.0.0.1:58591 \
  "https://api.github.com/repos/luxuguang-leo/persian-jazz-podcast/contents/feed.xml" \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('content',{}).get('name','') or 'Error: '+r.get('message',''))"
