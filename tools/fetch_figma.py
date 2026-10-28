#!/usr/bin/env python3
"""Fetch Figma metadata + PNG pieces for AG-60517 event frames (REST).

Usage:
  python3 tools/fetch_figma.py            # metadata only -> assets/meta.json
  python3 tools/fetch_figma.py --export   # metadata + PNG exports into assets/
"""
import json
import os
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FILE_KEY = "HAd3I2CYWl0dzYKKN5cKiC"  # branch key of AppStore-Img
TOKEN = os.environ.get("FIGMA_API_KEY", "")

# Real node ids (file was edited after the task brief; ids refreshed 28.10.2026)
FRAMES = {"16x9": "3187:2995", "9x16": "3187:3529"}

# piece id -> (frame, key, export scale)
PIECES = {
    "3187:2996": ("16x9", "glow", 1),
    "3187:2997": ("16x9", "badge", 2),
    "3187:2999": ("16x9", "title", 2),
    "3187:3000": ("16x9", "subtitle", 2),
    "3187:3001": ("16x9", "chips", 2),
    "3187:3022": ("16x9", "character", 2),
    "3187:3530": ("9x16", "glow", 1),
    "3187:3531": ("9x16", "character", 2),
    "3187:4163": ("9x16", "badge", 2),
    "3187:4165": ("9x16", "title", 2),
    "3187:4166": ("9x16", "subtitle", 2),
    "3187:4167": ("9x16", "chips", 2),
}


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"X-Figma-Token": TOKEN})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                print(f"  network error ({e}); retry {i + 2}/3 in 20s", flush=True)
                time.sleep(20)
    raise last


def fetch_meta():
    ids = "%2C".join(FRAMES.values())
    data = get(f"https://api.figma.com/v1/files/{FILE_KEY}/nodes?ids={ids}&depth=1")
    meta = {"file_key": FILE_KEY, "frames": {}, "pieces": {}}
    for label, nid in FRAMES.items():
        node = data["nodes"][nid]["document"]
        fb = node["absoluteBoundingBox"]
        children = []
        for ch in node.get("children", []):
            cb = ch.get("absoluteBoundingBox")
            if not cb:
                continue
            rel = {"x": round(cb["x"] - fb["x"], 2), "y": round(cb["y"] - fb["y"], 2),
                   "w": round(cb["width"], 2), "h": round(cb["height"], 2)}
            children.append({"id": ch["id"], "name": ch["name"], "type": ch["type"], **rel})
            if ch["id"] in PIECES:
                frame, key, scale = PIECES[ch["id"]]
                meta["pieces"][ch["id"]] = {"frame": frame, "key": key, "scale": scale, **rel}
        meta["frames"][label] = {"id": nid, "w": fb["width"], "h": fb["height"],
                                 "x": fb["x"], "y": fb["y"], "children": children}
        print(f"\n[{label}] {node['name']}  {fb['width']:.0f}x{fb['height']:.0f}")
        for ch in children:
            print(f"  {ch['id']:>10}  ({ch['x']:>7},{ch['y']:>7}) {ch['w']:>7}x{ch['h']:<7} {ch['name']}")
    return meta


def export_pngs(meta):
    by_scale = {}
    for pid, info in meta["pieces"].items():
        by_scale.setdefault(info["scale"], []).append(pid)
    urls = {}
    for scale, pids in sorted(by_scale.items()):
        ids = ",".join(pids)
        d = get(f"https://api.figma.com/v1/images/{meta['file_key']}?ids={ids}&format=png&scale={scale}")
        for pid, url in (d.get("images") or {}).items():
            if url:
                urls[pid] = url
            else:
                print(f"  WARNING: no render for {pid}")
    for pid, url in urls.items():
        info = meta["pieces"][pid]
        ext = f"assets/{info['frame']}/{info['key']}.png"
        (ASSETS / info["frame"]).mkdir(parents=True, exist_ok=True)
        for i in range(3):
            try:
                with urllib.request.urlopen(url, timeout=180) as r, open(ASSETS / info["frame"] / f"{info['key']}.png", "wb") as f:
                    f.write(r.read())
                break
            except Exception as e:  # noqa: BLE001
                if i == 2:
                    raise
                print(f"  download retry {i + 2}/3 ({e})", flush=True)
                time.sleep(20)
        p = ASSETS / info["frame"] / f"{info['key']}.png"
        print(f"  saved {p}  {p.stat().st_size / 1024:.0f} KB")


def main():
    if not TOKEN:
        sys.exit("ERROR: FIGMA_API_KEY is not set in environment")
    ASSETS.mkdir(exist_ok=True)
    meta = fetch_meta()
    out = ASSETS / "meta.json"
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"\nmeta.json written: {out}")
    if "--export" in sys.argv:
        print("\nexporting PNGs...")
        export_pngs(meta)


if __name__ == "__main__":
    main()
