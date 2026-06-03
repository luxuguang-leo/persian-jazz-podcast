#!/usr/bin/env python3
"""Arabic Jazz Weekly Upload: pick next episode, upload to Qiniu, update RSS on GitHub."""

import os, re, json, hashlib, subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

# ─── Config ─────────────────────────────────────────────────
BUCKET = "jazzradio"
DOMAIN = "https://pub-be12e0f10bed438db17fc28b4cad43dd.r2.dev"
PAGES_URL = "https://luxuguang-leo.github.io/arabic-jazz-podcast"
REPO = "luxuguang-leo/arabic-jazz-podcast"

OBSIDIAN = os.path.expanduser(
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/001-项目/波斯爵士播客"
)
MANIFEST = os.path.join(OBSIDIAN, "arabic-episodes.json")
STATE_FILE = os.path.join(OBSIDIAN, "arabic-upload_state.json")

SOURCES = {
    "NafasJazz": os.path.expanduser("~/Downloads/NafasJazz"),
    "SaffronJazzLounge": os.path.expanduser("~/Downloads/SaffronJazzLounge"),
    "SantonoNoise": os.path.expanduser("~/Downloads/SantonoNoise"),
    "ArobiyyahJazz": os.path.expanduser("~/Downloads/ArobiyyahJazz"),
}

PODCAST_TITLE = "阿拉伯爵士电台 Arabic Jazz Radio"
PODCAST_DESC = "阿拉伯爵士精选。从开罗到卡萨布兰卡，从巴格达到贝鲁特——穿越阿拉伯世界的爵士之旅。Arabian jazz compilations from across the Arab world."
COVER_URL = DOMAIN + "/arabic-cover.jpg"

# ─── Helpers ────────────────────────────────────────────────
def slugify(title):
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug[:60].strip('-') + '.m4a'

def load_episodes():
    with open(MANIFEST) as f:
        return json.load(f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"uploaded": [], "skipped": [], "upload_dates": {}, "show_notes": {}, "batch_plan": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def upload_to_qiniu(ak, sk, key, filepath):
    from qiniu import Auth
    q = Auth(ak, sk)
    token = q.upload_token(BUCKET, key, 7200)
    env_clean = os.environ.copy()
    for k in ['https_proxy','http_proxy','HTTPS_PROXY','HTTP_PROXY','all_proxy','ALL_PROXY']:
        env_clean.pop(k, None)
    r = subprocess.run([
        'curl', '-s', '-m', '300',
        '-F', 'token={}'.format(token),
        '-F', 'key={}'.format(key),
        '-F', 'file=@{}'.format(filepath),
        'http://upload.qiniup.com/'
    ], capture_output=True, text=True, timeout=310, env=env_clean)
    if r.returncode == 0:
        import json
        try:
            ret = json.loads(r.stdout)
            return ret.get('key') == key
        except:
            return False
    return False

def format_dur(sec):
    if not sec:
        return "unknown"
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, s)
    return "{:d}:{:02d}".format(m, s)

def generate_rss(uploaded_eps, show_notes=None):
    if show_notes is None:
        show_notes = {}
    rss = ET.Element("rss", {
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
        "version": "2.0",
    })
    chan = ET.SubElement(rss, "channel")
    ET.SubElement(chan, "title").text = PODCAST_TITLE
    ET.SubElement(chan, "link").text = PAGES_URL
    ET.SubElement(chan, "description").text = PODCAST_DESC
    ET.SubElement(chan, "language").text = "zh"
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(chan, "lastBuildDate").text = now
    ET.SubElement(chan, "itunes:author").text = "Leo"
    ET.SubElement(chan, "itunes:summary").text = "阿拉伯爵士电台 — 由波斯爵士电台团队制作"
    ET.SubElement(chan, "itunes:image", {"href": COVER_URL})
    ET.SubElement(chan, "itunes:explicit").text = "no"
    owner = ET.SubElement(chan, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = "Leo"
    cat = ET.SubElement(chan, "itunes:category", {"text": "Music"})
    ET.SubElement(cat, "itunes:category", {"text": "Music Commentary"})
    ET.SubElement(chan, "atom:link", {"href": PAGES_URL + "/feed.xml", "rel": "self", "type": "application/rss+xml"})

    for i, ep in enumerate(uploaded_eps, 1):
        item = ET.SubElement(chan, "item")
        title = ep["title"]
        city = ep.get("city", "")
        if city:
            title = "[{}] {}".format(city, title)
        ET.SubElement(item, "title").text = title

        dur_str = format_dur(ep["duration"])
        note = show_notes.get(str(ep.get("state_idx", i-1)), "")
        desc_parts = [ep["title"]]
        if note:
            desc_parts.append(note)
        desc_parts.append("City: {}  |  Source: {}  |  Duration: {}".format(
            city, ep["source"], dur_str))
        desc = "\n\n".join(desc_parts)
        ET.SubElement(item, "description").text = desc
        if note:
            ET.SubElement(item, "itunes:summary").text = note

        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = hashlib.md5(
            ep["filename"].encode()).hexdigest()
        pub = ep.get("pub_date", now)
        ET.SubElement(item, "pubDate").text = pub
        ET.SubElement(item, "enclosure", {
            "url": DOMAIN + "/" + ep['qiniu_key'],
            "length": str(ep["size"]),
            "type": "audio/mp4",
        })
        ET.SubElement(item, "itunes:duration").text = dur_str
        ET.SubElement(item, "itunes:episode").text = str(i)
        ET.SubElement(item, "itunes:episodeType").text = "full"

    raw = ET.tostring(rss, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    pretty = '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty.split("?>", 1)[-1].strip() + "\n"
    return pretty

def push_to_github(content, token):
    import urllib.request as ur
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    proxy_available = sock.connect_ex(('127.0.0.1', 58591)) == 0
    sock.close()

    if proxy_available:
        proxy_handler = ur.ProxyHandler({
            "https": "http://127.0.0.1:58591",
            "http": "http://127.0.0.1:58591"
        })
    else:
        proxy_handler = ur.ProxyHandler({})
    opener = ur.build_opener(proxy_handler)

    # Get SHA
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
    # Load credentials from .env
    env_path = os.path.expanduser("~/.hermes/.env")
    ak = sk = None
    github_token = None
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            if line.startswith("QINIU_ACCESS_KEY="):
                ak = line.strip().split("=", 1)[1]
            elif line.startswith("QINIU_SECRET_KEY="):
                sk = line.strip().split("=", 1)[1]
            elif line.startswith("GITHUB_TOKEN="):
                github_token = line.strip().split("=", 1)[1]

    episodes = load_episodes()
    state = load_state()
    uploaded_indices = set(state["uploaded"])
    skipped_indices = set(state.get("skipped", []))
    batch_plan = {bp['ep_index']: bp for bp in state.get('batch_plan', [])}

    # Find next unuploaded episode
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
    source = next_ep["source"]
    if source not in SOURCES:
        print("Unknown source: {}".format(source))
        print("Known sources: {}".format(list(SOURCES.keys())))
        return

    source_dir = SOURCES[source]
    filepath = os.path.join(source_dir, next_ep["filename"])

    # If file has special chars causing curl read errors, copy to temp
    key = slugify(next_ep["title"])
    size_mb = os.path.getsize(filepath) / 1024 / 1024

    print("[{}/{}] Uploading: {} ({:.0f}MB)".format(
        next_idx + 1, len(episodes), next_ep['title'][:60], size_mb))

    # Try direct upload first; if fails, copy to temp and retry
    ok = upload_to_qiniu(ak, sk, key, filepath)
    if not ok:
        import shutil
        tmp = "/tmp/arabic_upload_{}.m4a".format(next_idx)
        print("  Direct failed, trying via temp file...")
        shutil.copy2(filepath, tmp)
        ok = upload_to_qiniu(ak, sk, key, tmp)
        os.unlink(tmp)

    if ok:
        print("  OK: {}/{}".format(DOMAIN, key))
        state["uploaded"].append(next_idx)
        if "upload_dates" not in state:
            state["upload_dates"] = {}
        state["upload_dates"][str(next_idx)] = datetime.now(timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S +0000")
        save_state(state)
    else:
        print("  FAIL: Upload error")
        return

    # Rebuild RSS with all uploaded episodes
    upload_dates = state.get("upload_dates", {})
    show_notes = state.get("show_notes", {})
    uploaded_eps = []
    for idx in state["uploaded"]:
        ep = episodes[idx]
        ep_copy = dict(ep)
        ep_copy["qiniu_key"] = slugify(ep["title"])
        ep_copy["state_idx"] = idx
        ep_copy["city"] = batch_plan.get(idx, {}).get("city", "")
        if str(idx) in upload_dates:
            ep_copy["pub_date"] = upload_dates[str(idx)]
        # Add show note if available
        note = show_notes.get(str(idx), batch_plan.get(idx, {}).get("show_note", ""))
        if note:
            if "show_notes" not in state:
                state["show_notes"] = {}
            state["show_notes"][str(idx)] = note
        uploaded_eps.append(ep_copy)

    rss_xml = generate_rss(uploaded_eps, show_notes=state.get("show_notes", {}))
    print("RSS rebuilt: {} episodes, {} bytes".format(len(uploaded_eps), len(rss_xml)))

    # Save locally as fallback
    local_rss = "/tmp/arabic_feed.xml"
    with open(local_rss, "w") as f:
        f.write(rss_xml)

    # Save to Obsidian
    obsidian_rss = os.path.join(OBSIDIAN, "arabic-feed.xml")
    with open(obsidian_rss, "w") as f:
        f.write(rss_xml)

    # Push to GitHub
    if not github_token:
        print("WARNING: GITHUB_TOKEN not set, RSS saved locally only")
        return

    if push_to_github(rss_xml, github_token):
        print("OK: Pushed to GitHub Pages: {}/feed.xml".format(PAGES_URL))
    else:
        print("FAIL: GitHub push error — RSS saved at {}".format(local_rss))

if __name__ == "__main__":
    main()
