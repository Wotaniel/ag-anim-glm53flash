#!/usr/bin/env python3
"""Validate AG-60517 .keyshape files before handoff.

Checks (per AGENTS.md rules + keyshapeapp.com/file-format):
  - zip intact, contains document.keyshapex; XML parses
  - every ks:animate: timing-functions == keys - 1, times strictly increasing,
    loop anims end at loop length, repeat-end="indefinite"
  - ks:playRangeOut == loop length in ms
  - all <image> hrefs are decodable base64 PNG data URIs
  - unique ids; human-readable layer tree printed
"""
import base64
import pathlib
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NS = {"ks": "http://ns.keyshapeapp.com", "svg": "http://www.w3.org/2000/svg"}
LOOP = 20.0
FILES = ["AG-60517 Event Card 16x9.keyshape", "AG-60517 Event Details 9x16.keyshape"]
fail = 0


def check(cond, msg):
    global fail
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fail += 1


for fn in FILES:
    print(f"\n== {fn} ==")
    p = ROOT / fn
    check(p.exists(), "file exists")
    with zipfile.ZipFile(p) as z:
        check(z.testzip() is None, "zip integrity (testzip)")
        names = z.namelist()
        check(names == ["document.keyshapex"], f"zip contents: {names}")
        xml = z.read("document.keyshapex")
    try:
        root = ET.fromstring(xml)
        check(True, "XML parses")
    except ET.ParseError as e:
        check(False, f"XML parses: {e}")
        continue

    KSN = "{http://ns.keyshapeapp.com}"
    check(root.get(KSN + "version") == "1.1", "ks:version=1.1")
    check(root.get(KSN + "playRangeIn") == "0" and root.get(KSN + "playRangeOut") == "20000",
          f"playRange ms = {root.get(KSN + 'playRangeIn')}..{root.get(KSN + 'playRangeOut')}")

    anims = root.findall(".//ks:animate", NS)
    check(len(anims) > 0, f"ks:animate count = {len(anims)}")
    for a in anims:
        at = a.get("abs-key-times", "")
        times = [float(x) for x in at.split(";")]
        tf = [x for x in (a.get("timing-functions") or "").split(";") if x]
        vals = [x for x in (a.get("values") or "").split(";") if x]
        ok = True
        if len(tf) != len(times) - 1:
            check(False, f"{a.get('attribute')}/{a.get('type')}: timing-functions {len(tf)} != keys {len(times)} - 1")
            ok = False
        if any(b <= a_ for a_, b in zip(times, times[1:])):
            check(False, f"{a.get('attribute')}: key times not strictly increasing: {at}")
            ok = False
        if a.get("repeat-end") == "indefinite" and times[-1] != LOOP:
            check(False, f"{a.get('attribute')}: loop ends at {times[-1]} != {LOOP}")
            ok = False
        if len(vals) != len(times):
            check(False, f"{a.get('attribute')}: values {len(vals)} != keys {len(times)}")
            ok = False
        if ok:
            check(True, f"{a.get('attribute')}/{a.get('type') or '-'}: {len(times)} keys, "
                        f"{len(tf)} easings, ends {times[-1]:g}s, {a.get('repeat-end')}")

    imgs = root.findall(".//{http://www.w3.org/2000/svg}image")
    for im in imgs:
        href = im.get("href", "")
        ok = href.startswith("data:image/png;base64,")
        if ok:
            try:
                head = base64.b64decode(href.split(",", 1)[1], validate=False)[:8]
                ok = head.startswith(b"\x89PNG\r\n\x1a\n")
            except Exception:  # noqa: BLE001
                ok = False
        where = im.get("x"), im.get("y"), im.get("width"), im.get("height")
        check(ok, f"image @{where} valid base64 PNG ({len(href) // 1024} KB encoded)")

    ids = [e.get("id") for e in root.iter() if e.get("id")]
    check(len(ids) == len(set(ids)), f"ids unique ({len(ids)})")

    def tree(e, d=0):
        for ch in e:
            tag = ch.tag.split("}")[-1]
            if tag in ("g", "image", "rect", "path", "circle", "ellipse"):
                name = ch.get("id") or tag
                kid = len([c for c in ch if c.tag.split('}')[-1] == 'g'])
                print("      " + "  " * d + name + (f"  ({kid} subg)" if kid else ""))
                if tag == "g":
                    tree(ch, d + 1)
    print("  layer tree:")
    for top in root:
        tag = top.tag.split("}")[-1]
        if tag in ("g", "rect"):
            name = top.get("id") or tag
            print("      " + name)
            tree(top, 1)

print("\n" + ("ALL CHECKS PASSED" if fail == 0 else f"{fail} CHECK(S) FAILED"))
sys.exit(1 if fail else 0)
