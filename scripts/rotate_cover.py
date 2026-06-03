#!/usr/bin/env python3
"""Daily cover rotation: upload unique-key cover, update RSS, push to GitHub."""

import os, sys, glob, random, re, json, hashlib, base64, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom
from qiniu import Auth, put_file

# ── Config ──
BUCKET = "jazzradio"
DOMAIN = "https://pub-be12e0f10bed438db17fc28b4cad43dd.r2.dev"
COVERS_DIR = str(Path.home() / "Downloads" / "podcast_covers")
ENV_FILE = str(Path.home() / ".hermes" / ".env")
MANIFEST = str(Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/001-项目/波斯爵士播客/episodes.json")
STATE_FILE = str(Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/001-项目/波斯爵士播客/upload_state.json")
PAGES = "https://luxuguang-leo.github.io/persian-jazz-podcast"
REPO = "luxuguang-leo/persian-jazz-podcast"
COVER_KEY = "cover-" + datetime.now().strftime("%Y%m%d") + ".jpg"

# ── Helpers ──
def slugify(t):
    s = re.sub(r'[^\w\s-]', '', t.lower())
    s = re.sub(r'[\s_]+', '-', s)
    return s[:60].strip('-') + '.m4a'

def fmt_dur(sec):
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, s)
    return "{:d}:{:02d}".format(m, s)

# ── Load credentials ──
ak = sk = gh_token = None
with open(ENV_FILE, encoding='utf-8') as f:
    for line in f:
        if line.startswith("QINIU_ACCESS_KEY="):
            ak = line.strip().split("=", 1)[1]
        elif line.startswith("QINIU_SECRET_KEY="):
            sk = line.strip().split("=", 1)[1]
        elif line.startswith("GITHUB_TOKEN="):
            gh_token = line.strip().split("=", 1)[1]

if not ak or not sk:
    print("ERROR: Qiniu credentials missing")
    sys.exit(1)

# ── 1. Pick & upload cover (no proxy for Qiniu) ──
saved_https = os.environ.pop("https_proxy", None)
saved_http = os.environ.pop("http_proxy", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("all_proxy", None)
os.environ.pop("ALL_PROXY", None)

covers = sorted(glob.glob(COVERS_DIR + "/*.png"))
pick = random.choice(covers)
print("Cover: {} ({}KB)".format(os.path.basename(pick)[:50], os.path.getsize(pick) // 1024))

q = Auth(ak, sk)
token = q.upload_token(BUCKET, COVER_KEY, 3600)
ret, info = put_file(token, COVER_KEY, pick)
if ret is None:
    print("FAIL: {}".format(info))
    sys.exit(1)
cover_url = DOMAIN + "/" + COVER_KEY
print("Uploaded: {}".format(cover_url))

# Also upload as cover.jpg for backward compat + refresh CDN cache
token2 = q.upload_token(BUCKET, "cover.jpg", 3600)
put_file(token2, "cover.jpg", pick)
try:
    from qiniu import CdnManager
    cdn = CdnManager(q)
    cdn.refresh_urls([DOMAIN + "/cover.jpg"])
    print("CDN cache refreshed for cover.jpg")
except Exception as e:
    print("CDN refresh: {} (non-fatal)".format(e))

# Restore proxy for GitHub
if saved_https:
    os.environ["https_proxy"] = saved_https
if saved_http:
    os.environ["http_proxy"] = saved_http

# ── 2. Generate RSS ──
with open(MANIFEST) as f:
    episodes = json.load(f)
with open(STATE_FILE) as f:
    state = json.load(f)

rss = ET.Element("rss", {
    "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "xmlns:atom": "http://www.w3.org/2005/Atom",
    "version": "2.0",
})
ch = ET.SubElement(rss, "channel")
ET.SubElement(ch, "title").text = "波斯爵士电台 Persian Jazz Radio"
ET.SubElement(ch, "link").text = PAGES
ET.SubElement(ch, "description").text = "Persian jazz compilations."
ET.SubElement(ch, "language").text = "en"
now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
ET.SubElement(ch, "lastBuildDate").text = now
ET.SubElement(ch, "itunes:author").text = "Leo"
ET.SubElement(ch, "itunes:summary").text = "Persian jazz compilations."
ET.SubElement(ch, "itunes:image", {"href": cover_url})
ET.SubElement(ch, "itunes:explicit").text = "no"
own = ET.SubElement(ch, "itunes:owner")
ET.SubElement(own, "itunes:name").text = "Leo"
cat = ET.SubElement(ch, "itunes:category", {"text": "Music"})
ET.SubElement(cat, "itunes:category", {"text": "Music Commentary"})
ET.SubElement(ch, "atom:link", {"href": PAGES + "/feed.xml", "rel": "self", "type": "application/rss+xml"})

upload_dates = state.get("upload_dates", {})
for i, idx in enumerate(state["uploaded"], 1):
    ep = episodes[idx]
    key = slugify(ep["title"])
    if ep["filename"].startswith("Booye mahe mehr"):
        key = ep["filename"]
    dur = fmt_dur(ep["duration"])
    item = ET.SubElement(ch, "item")
    ET.SubElement(item, "title").text = ep["title"]
    note = state.get("show_notes", {}).get(str(idx), "")
    desc_parts = [ep["title"]]
    if note:
        desc_parts.append(note)
    desc_parts.append("Collection: " + ep["source"] + "  |  Duration: " + dur)
    ET.SubElement(item, "description").text = "\n\n".join(desc_parts)
    if note:
        ET.SubElement(item, "itunes:summary").text = note
    ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = hashlib.md5(ep["filename"].encode()).hexdigest()
    pub = upload_dates.get(str(idx), now)
    ET.SubElement(item, "pubDate").text = pub
    ET.SubElement(item, "enclosure", {"url": DOMAIN + "/" + key, "length": str(ep["size"]), "type": "audio/mp4"})
    ET.SubElement(item, "itunes:duration").text = dur
    ET.SubElement(item, "itunes:season").text = "1"
    ET.SubElement(item, "itunes:episode").text = str(i)
    ET.SubElement(item, "itunes:episodeType").text = "full"

raw = ET.tostring(rss, encoding="unicode")
pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
pretty = '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty.split("?>", 1)[-1].strip() + "\n"

# ── 3. Push to GitHub ──
if not gh_token:
    print("WARNING: GITHUB_TOKEN not set, RSS not pushed")
    sys.exit(0)

proxy_handler = urllib.request.ProxyHandler({"https": "http://127.0.0.1:58591", "http": "http://127.0.0.1:58591"})
opener = urllib.request.build_opener(proxy_handler)

req = urllib.request.Request(
    "https://api.github.com/repos/{}/contents/feed.xml".format(REPO),
    headers={"Authorization": "token " + gh_token, "Accept": "application/vnd.github.v3+json"},
)
data = json.loads(opener.open(req, timeout=15).read())
sha = data["sha"]

payload = json.dumps({
    "message": "Daily cover rotation",
    "content": base64.b64encode(pretty.encode()).decode(),
    "sha": sha,
}).encode()
req2 = urllib.request.Request(
    "https://api.github.com/repos/{}/contents/feed.xml".format(REPO),
    data=payload,
    headers={"Authorization": "token " + gh_token, "Content-Type": "application/json"},
    method="PUT",
)
resp = opener.open(req2, timeout=30)
print("RSS pushed OK, cover URL: {}".format(cover_url))
