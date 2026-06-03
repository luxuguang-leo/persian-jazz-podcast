#!/usr/bin/env python3
"""
Scan download directories for new audio files and append them to episodes.json.
Run after youtube-dl downloads complete.

Usage:
    python3 scan_new.py

Detection: compares filenames against existing manifest entries.
Supports: .m4a, .mp3
Duration: via mdls (macOS only)
"""
import os, re, json, subprocess

WAJ_DIR = os.path.expanduser("~/Downloads/WeAreJazz")
QJJ_DIR = os.path.expanduser("~/Downloads/QajarJazz/QajarJazz")
MANIFEST = os.path.expanduser(
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/001-项目/波斯爵士播客/episodes.json"
)

SOURCES = {
    "WeAreJazz": WAJ_DIR,
    "QajarJazz": QJJ_DIR,
}

def get_duration(path):
    r = subprocess.run(
        ["mdls", "-name", "kMDItemDurationSeconds", path],
        capture_output=True, text=True, timeout=10
    )
    m = re.search(r'=\s*([\d.]+)', r.stdout)
    return float(m.group(1)) if m else 0

def main():
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            episodes = json.load(f)
    else:
        episodes = []

    existing_filenames = set(ep["filename"] for ep in episodes)
    new_entries = []

    for source_name, source_dir in SOURCES.items():
        if not os.path.isdir(source_dir):
            print(f"  SKIP {source_name}: directory not found")
            continue
        for fname in sorted(os.listdir(source_dir)):
            if not fname.endswith((".m4a", ".mp3")):
                continue
            if fname in existing_filenames:
                continue
            path = os.path.join(source_dir, fname)
            size = os.path.getsize(path)
            if size == 0:
                print(f"  SKIP {fname}: zero bytes")
                continue
            duration = int(get_duration(path))
            title = fname.replace(".m4a", "").replace(".mp3", "").strip()
            entry = {
                "source": source_name,
                "filename": fname,
                "title": title,
                "size": size,
                "duration": duration,
            }
            new_entries.append(entry)
            print(f"  NEW [{source_name}] {title[:60]} ({duration//60}min)")

    if not new_entries:
        print("No new files found.")
        return

    episodes.extend(new_entries)
    with open(MANIFEST, "w") as f:
        json.dump(episodes, f, indent=2, ensure_ascii=False)

    print(f"\nAdded {len(new_entries)} new entries to episodes.json (total: {len(episodes)})")

if __name__ == "__main__":
    main()
