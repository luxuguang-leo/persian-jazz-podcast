#!/usr/bin/env python3
"""Weekly upload: pick next episode, upload to R2, update filtered RSS on GitHub."""

import os, re, json, hashlib, subprocess, urllib.parse, shlex
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom
import boto3

# ─── Config ─────────────────────────────────────────────────
BUCKET = "podcast-audio"
DOMAIN = "https://pub-be12e0f10bed438db17fc28b4cad43dd.r2.dev"
PAGES_URL = "https://luxuguang-leo.github.io/persian-jazz-podcast"
MANIFEST = "/tmp/episodes.json"
STATE_FILE = "/tmp/upload_state.json"
_PERSISTENT_STATE = os.path.expanduser("~/.hermes/persian-jazz-state.json")
_PERSISTENT_EPISODES = os.path.expanduser("~/.hermes/persian-jazz-episodes.json")

# R2 config
R2_ENDPOINT = "https://f24347565d480242571ab38775e2a183.r2.cloudflarestorage.com"
R2_ACCESS_KEY = "732bb875128829ac53476f7da93c96f7"
R2_SECRET_KEY = "9c19fd3056d562823dda6506d75e71532d82136466101d7755be399e0c2deecb"

# Sync fresh copies from iCloud (can't read evicted fault files directly from cron)
import shlex, subprocess, time
_icloud_dir = os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/001-项目/波斯爵士播客")
for _f, _persist_key in [("episodes.json", _PERSISTENT_EPISODES), ("upload_state.json", _PERSISTENT_STATE)]:
    _src = os.path.join(_icloud_dir, _f)
    _dst = "/tmp/" + _f
    # brctl download forces iCloud to materialize the file first
    subprocess.run(["brctl", "download", _src], capture_output=True, timeout=30)
    time.sleep(1)
    # Then cat-bridge to /tmp/ (avoids fcopyfile deadlock)
    r = subprocess.run(["bash", "-c", "cat " + shlex.quote(_src) + " > " + shlex.quote(_dst)], capture_output=True, timeout=30)
    # If iCloud copy failed, fall back to persistent copy
    if r.returncode != 0 or os.path.getsize(_dst) == 0:
        if os.path.exists(_persist_key) and os.path.getsize(_persist_key) > 0:
            subprocess.run(["cp", _persist_key, _dst], capture_output=True, timeout=10)
    # Also persist to stable location for future fallback
    if os.path.getsize(_dst) > 0:
        subprocess.run(["cp", _dst, _persist_key], capture_output=True, timeout=10)

REPO = "luxuguang-leo/persian-jazz-podcast"

SOURCES = {
    "WeAreJazz": os.path.expanduser("~/Downloads/WeAreJazz"),
    "QajarJazz": os.path.expanduser("~/Downloads/QajarJazz"),
}

# ─── Helpers ────────────────────────────────────────────────
def slugify(title):
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug[:60].strip('-') + '.m4a'

def load_episodes():
    if os.path.exists(MANIFEST) and os.path.getsize(MANIFEST) > 0:
        with open(MANIFEST) as f:
            return json.load(f)
    # Fallback to persistent copy
    if os.path.exists(_PERSISTENT_EPISODES) and os.path.getsize(_PERSISTENT_EPISODES) > 0:
        with open(_PERSISTENT_EPISODES) as f:
            return json.load(f)
    return []

def load_state():
    for path in [STATE_FILE, _PERSISTENT_STATE]:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path) as f:
                return json.load(f)
    return {"uploaded": [], "skipped": [], "upload_dates": {}, "current_index": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    # Also persist to a stable location for cron jobs (iCloud writes may fail)
    with open(_PERSISTENT_STATE, "w") as f:
        json.dump(state, f, indent=2)

def upload_to_r2(key, filepath):
    """Upload file to Cloudflare R2 using boto3 S3 API.

    Handles Unicode filenames via symlink workaround."""
    import tempfile

    _tmp_link = None
    try:
        has_unicode = any(ord(c) > 127 for c in filepath)
        if has_unicode:
            _tmp_link = tempfile.mktemp(suffix='.m4a')
            os.symlink(filepath, _tmp_link)
            upload_path = _tmp_link
        else:
            upload_path = filepath

        # Bypass proxy for R2 upload
        saved_env = {}
        for k in ['https_proxy', 'http_proxy', 'HTTPS_PROXY', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY']:
            saved_env[k] = os.environ.pop(k, None)

        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=R2_ENDPOINT,
                aws_access_key_id=R2_ACCESS_KEY,
                aws_secret_access_key=R2_SECRET_KEY,
            )
            s3.upload_file(upload_path, BUCKET, key)
            return True
        except Exception as e:
            print("  R2 upload error: {}".format(e))
            return False
        finally:
            for k, v in saved_env.items():
                if v is not None:
                    os.environ[k] = v
    finally:
        if _tmp_link and os.path.islink(_tmp_link):
            os.unlink(_tmp_link)

def format_dur(sec):
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, s)
    return "{:d}:{:02d}".format(m, s)

def generate_rss(uploaded_eps, cover_url=None, show_notes=None):
    """Generate filtered RSS with only uploaded episodes."""
    if show_notes is None:
        show_notes = {}
    if cover_url is None:
        cover_url = DOMAIN + "/cover.jpg"
    rss = ET.Element("rss", {
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
        "version": "2.0",
    })
    chan = ET.SubElement(rss, "channel")
    ET.SubElement(chan, "title").text = "波斯爵士电台 Persian Jazz Radio"
    ET.SubElement(chan, "link").text = PAGES_URL
    ET.SubElement(chan, "description").text = "Persian jazz compilations."
    ET.SubElement(chan, "language").text = "en"
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(chan, "lastBuildDate").text = now
    ET.SubElement(chan, "itunes:author").text = "Leo"
    ET.SubElement(chan, "itunes:summary").text = "Persian jazz compilations."
    ET.SubElement(chan, "itunes:image", {"href": cover_url})  # → R2 CDN, NOT GitHub Pages
    ET.SubElement(chan, "itunes:explicit").text = "no"
    owner = ET.SubElement(chan, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = "Leo"
    cat = ET.SubElement(chan, "itunes:category", {"text": "Music"})
    ET.SubElement(cat, "itunes:category", {"text": "Music Commentary"})
    ET.SubElement(chan, "atom:link", {"href": PAGES_URL + "/feed.xml", "rel": "self", "type": "application/rss+xml"})

    for i, ep in enumerate(uploaded_eps, 1):
        item = ET.SubElement(chan, "item")
        ET.SubElement(item, "title").text = ep["title"]
        dur_str = format_dur(ep["duration"])
        note = show_notes.get(str(ep.get("state_idx", i-1)), "")
        desc_parts = [ep["title"]]
        if note:
            desc_parts.append(note)
        desc_parts.append("Collection: " + ep["source"] + "  |  Duration: " + dur_str)
        desc = "\n\n".join(desc_parts)
        ET.SubElement(item, "description").text = desc
        if note:
            ET.SubElement(item, "itunes:summary").text = note
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = hashlib.md5(ep["filename"].encode()).hexdigest()
        # Per-episode pubDate from upload_dates (prevents all episodes getting same date on regen)
        pub = ep.get("pub_date", now)
        ET.SubElement(item, "pubDate").text = pub
        ET.SubElement(item, "enclosure", {
            "url": DOMAIN + "/" + ep['r2_key'],
            "length": str(ep["size"]),
            "type": "audio/mp4",
        })
        ET.SubElement(item, "itunes:duration").text = dur_str
        ET.SubElement(item, "itunes:season").text = "1"
        ET.SubElement(item, "itunes:episode").text = str(i)
        ET.SubElement(item, "itunes:episodeType").text = "full"

    raw = ET.tostring(rss, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    pretty = '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty.split("?>", 1)[-1].strip() + "\n"
    return pretty

def push_to_github(content, token):
    """Upload feed.xml to GitHub via API. Returns True on success."""
    import urllib.request as ur
    import socket

    # Auto-detect proxy: try common Clash/Mihomo ports
    proxy_port = None
    for port in [58591, 7897, 7890, 1087, 1080]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        if sock.connect_ex(('127.0.0.1', port)) == 0:
            proxy_port = port
            sock.close()
            break
        sock.close()

    if proxy_port:
        proxy_url = "http://127.0.0.1:{}".format(proxy_port)
        proxy_handler = ur.ProxyHandler({"https": proxy_url, "http": proxy_url})
    else:
        proxy_handler = ur.ProxyHandler({})
    opener = ur.build_opener(proxy_handler)

    # Get existing SHA
    req = ur.Request(
        "https://api.github.com/repos/{}/contents/feed.xml".format(REPO),
        headers={"Authorization": "token " + token, "Accept": "application/vnd.github.v3+json"},
    )
    data = json.loads(opener.open(req, timeout=15).read())
    sha = data["sha"]

    # Push
    payload = json.dumps({
        "message": "Weekly update - {}".format(datetime.now().strftime("%Y-%m-%d")),
        "content": __import__('base64').b64encode(content.encode()).decode(),
        "sha": sha,
    }).encode()
    req2 = ur.Request(
        "https://api.github.com/repos/{}/contents/feed.xml".format(REPO),
        data=payload,
        headers={"Authorization": "token " + token, "Content-Type": "application/json"},
        method="PUT",
    )
    resp = opener.open(req2, timeout=30)
    return resp.getcode() in (200, 201)

# ─── Main ───────────────────────────────────────────────────
def main():
    # Load GitHub token from .env
    env_path = os.path.expanduser("~/.hermes/.env")
    github_token = None
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                github_token = line.strip().split("=", 1)[1]

    episodes = load_episodes()
    state = load_state()
    uploaded_indices = set(state["uploaded"])
    skipped_indices = set(state.get("skipped", []))

    # Find next unuploaded episode (skip short/unwanted ones)
    next_ep = None
    next_idx = None
    for idx, ep in enumerate(episodes):
        if idx not in uploaded_indices and idx not in skipped_indices:
            next_ep = ep
            next_idx = idx
            break

    if next_ep is None:
        print("All episodes uploaded!")
        return

    # Upload
    source_dir = SOURCES[next_ep["source"]]
    filepath = os.path.join(source_dir, next_ep["filename"])
    key = slugify(next_ep["title"])
    size_mb = os.path.getsize(filepath) / 1024 / 1024

    print("[{}/{}] Uploading: {} ({}MB)".format(next_idx+1, len(episodes), next_ep['title'][:60], int(size_mb)))
    if upload_to_r2(key, filepath):
        print("  OK: {}/{}".format(DOMAIN, key))
        state["uploaded"].append(next_idx)
        # Record pubDate so this episode keeps its original date forever
        if "upload_dates" not in state:
            state["upload_dates"] = {}
        state["upload_dates"][str(next_idx)] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        save_state(state)
    else:
        print("  FAIL: Upload error")
        return

    # Rebuild RSS with all uploaded episodes
    upload_dates = state.get("upload_dates", {})
    uploaded_eps = []
    for idx in state["uploaded"]:
        ep = episodes[idx]
        ep_copy = dict(ep)
        ep_copy["r2_key"] = slugify(ep["title"])
        ep_copy["state_idx"] = idx  # for show_notes lookup
        if ep["filename"].startswith("Booye mahe mehr"):
            ep_copy["r2_key"] = ep["filename"]
        # Preserve original pubDate
        if str(idx) in upload_dates:
            ep_copy["pub_date"] = upload_dates[str(idx)]
        uploaded_eps.append(ep_copy)

    rss_xml = generate_rss(uploaded_eps, show_notes=state.get("show_notes", {}))

    # VERIFICATION: count itunes:summary tags — must be (episodes + 1)
    summary_count = rss_xml.count("<itunes:summary>")
    expected = len(uploaded_eps) + 1
    if summary_count < expected:
        print("⚠️  CRITICAL: itunes:summary count = {} (expected {}). Show notes lost!".format(summary_count, expected))
        print("   Check generate_rss() call — 'show_notes=' parameter may be missing or empty.")
        # Don't push — feed would lose descriptions again
        print("   Aborting GitHub push to avoid publishing broken feed.")
        local_path = "/tmp/feed.xml"
        with open(local_path, "w") as f:
            f.write(rss_xml)
        print("   Saved locally for inspection: {}".format(local_path))
        return
    else:
        print("✓ Verified: {} itunes:summary tags (expected {}). Show notes intact.".format(summary_count, expected))

    print("RSS rebuilt: {} episodes, {} bytes".format(len(uploaded_eps), len(rss_xml)))

    # Push to GitHub (needs proxy in China)
    if not github_token:
        print("WARNING: GITHUB_TOKEN not set, skipping GitHub push")
        local_path = "/tmp/feed.xml"
        with open(local_path, "w") as f:
            f.write(rss_xml)
        print("  Saved locally: {}".format(local_path))
        return

    if push_to_github(rss_xml, github_token):
        print("OK: Pushed to GitHub Pages: {}/feed.xml".format(PAGES_URL))
    else:
        print("FAIL: GitHub push error")

if __name__ == "__main__":
    main()
