#!/usr/bin/env python3
"""
Helper for the job-pacing skill.

CompanyCam's get_project_photos payload is large and its MCP result is usually
spilled to a tool-results .txt file (a JSON array where each element is
{"type":"text","text":"<one photo's JSON>"}). This script parses that file and
either prints a day-by-day cadence timeline or downloads the most recent photos
so you can Read them and judge the actual build stage.

Usage:
  # cadence timeline (dates, counts, creators, overall date range)
  python companycam_photos.py timeline <path-to-tool-result.txt>

  # download the N most recent photos to a dir, print saved paths to Read
  python companycam_photos.py download <path-to-tool-result.txt> <out-dir> [N]

It also accepts a raw JSON array of photo objects (if you saved the photos list
directly) — it auto-detects either shape.
"""
import json, sys, os, datetime, urllib.request


def load_photos(path):
    data = json.load(open(path))
    photos = []
    if isinstance(data, list):
        for el in data:
            if isinstance(el, dict) and el.get("type") == "text" and "text" in el:
                try:
                    inner = json.loads(el["text"])
                except Exception:
                    continue
                if isinstance(inner, list):
                    photos.extend(inner)
                elif isinstance(inner, dict):
                    # single photo, or a wrapper with a list under a common key
                    listed = False
                    for k in ("photos", "data", "results"):
                        if isinstance(inner.get(k), list):
                            photos.extend(inner[k]); listed = True
                    if not listed:
                        photos.append(inner)
            elif isinstance(el, dict):
                photos.append(el)  # already a photo object
    elif isinstance(data, dict):
        for k in ("photos", "data", "results"):
            if isinstance(data.get(k), list):
                photos.extend(data[k])
    return photos


def fmt(ts):
    # captured_at is unix epoch seconds; show US-Eastern-ish (UTC-4) for readability
    return datetime.datetime.utcfromtimestamp(ts - 4 * 3600).strftime("%Y-%m-%d %H:%M")


def best_uri(ph):
    uris = {u.get("type"): u.get("uri") for u in (ph.get("uris") or []) if isinstance(u, dict)}
    for o in ("web", "original", "large", "medium"):
        if uris.get(o):
            return uris[o]
    return ph.get("photo_url")


def timeline(path):
    photos = [p for p in load_photos(path) if p.get("captured_at")]
    photos.sort(key=lambda x: x["captured_at"])
    print(f"total photos: {len(photos)}")
    if not photos:
        return
    print(f"first captured: {fmt(photos[0]['captured_at'])}")
    print(f"last  captured: {fmt(photos[-1]['captured_at'])}")
    days = {}
    for p in photos:
        d = fmt(p["captured_at"])[:10]
        days.setdefault(d, {"n": 0, "who": set()})
        days[d]["n"] += 1
        if p.get("creator_name"):
            days[d]["who"].add(p["creator_name"])
    print("\ndate        | photos | creators")
    print("-" * 52)
    for d in sorted(days):
        print(f"{d} | {days[d]['n']:>6} | {', '.join(sorted(days[d]['who']))}")


def download(path, out_dir, n=8):
    photos = [p for p in load_photos(path) if p.get("captured_at")]
    photos.sort(key=lambda x: x["captured_at"])
    os.makedirs(out_dir, exist_ok=True)
    for p in photos[-int(n):]:
        u = best_uri(p)
        if not u:
            continue
        stamp = fmt(p["captured_at"]).replace(" ", "_").replace(":", "")
        fn = os.path.join(out_dir, f"p_{stamp}_{p.get('id','x')}.jpg")
        try:
            urllib.request.urlretrieve(u, fn)
            print(f"{stamp}  {p.get('creator_name','?'):16}  {fn}")
        except Exception as e:
            print(f"ERR {p.get('id')}: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "timeline":
        timeline(sys.argv[2])
    elif cmd == "download":
        download(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 8)
    else:
        print(__doc__); sys.exit(1)
