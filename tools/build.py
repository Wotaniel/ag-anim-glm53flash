#!/usr/bin/env python3
"""Build AG-60517 Keyshape projects + SMIL previews + index.html.

Inputs:  assets/<frame>/*.png (Figma REST exports), assets/meta.json
Outputs: AG-60517 Event Card 16x9.keyshape
         AG-60517 Event Details 9x16.keyshape
         previews/card-16x9.svg, previews/card-9x16.svg (SMIL, for browser)
         index.html (GitHub Pages landing)

Format rules (keyshapeapp.com/file-format, verified against ag.keyshape sample):
  - abs-key-times in SECONDS; ks:playRangeIn/Out in MILLISECONDS
  - timing-functions count = keys - 1; repeat-end="indefinite"
  - rotate/scale run around the group pivot: group position = pivot,
    content is drawn relative to it (inverse-translate wrapper keeps scene coords)
"""
import base64
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PREVIEWS = ROOT / "previews"

LOOP = 20.0  # seconds
EIO = "ease-in-out"
LIN = "linear"
SNAP = "cubic-bezier(0.2,0.8,0.3,1)"      # fast pop
SOFT = "cubic-bezier(0.25,0.1,0.25,1)"    # gentle

# scene geometry from Figma metadata (rel coords inside each frame)
FILES = {
    "16x9": {
        "out": "AG-60517 Event Card 16x9.keyshape",
        "preview": "card-16x9.svg",
        "export": "ag-60517-event-card-16x9.svg",
        "title": "AG-60517 · Event Card 16:9 — AdGuard v5 is here",
        "vw": 1920, "vh": 1080,
        "camera_focus": (1465, 300),
        "camera_zoom": [1.0, 1.12, 1.20],
        "breath_pivot": (1520, 1150),
        "breath_amp": 0.012,
        "glints": [
            {"id": "Glint-crown", "t": 5.0, "p": (1465, 150), "r": 20, "peak_s": 1.15, "peak_o": 1.0},
            {"id": "Glint-pauldron", "t": 9.5, "p": (1240, 455), "r": 18, "peak_s": 1.10, "peak_o": 0.9},
        ],
        "markers": [
            (1.0, "Камера: наезд 1", "green"), (4.0, "Камера: замер 1", "gray"),
            (6.0, "Камера: наезд 2", "green"), (8.5, "Камера: замер 2", "gray"),
            (10.5, "Камера: отъезд", "blue"), (17.5, "Камера: стоп", "gray"),
            (5.0, "Блик: корона", "yellow"), (9.5, "Блик: наплечник", "yellow"),
        ],
    },
    "9x16": {
        "out": "AG-60517 Event Details 9x16.keyshape",
        "preview": "card-9x16.svg",
        "export": "ag-60517-event-details-9x16.svg",
        "title": "AG-60517 · Event Details 9:16 — AdGuard v5 is here",
        "vw": 1080, "vh": 1920,
        "camera_focus": (520, 760),
        "camera_zoom": [1.0, 1.10, 1.16],
        "breath_pivot": (690, 1880),
        "breath_amp": 0.010,
        "glints": [
            {"id": "Glint-crown", "t": 5.0, "p": (515, 500), "r": 22, "peak_s": 1.15, "peak_o": 1.0},
            {"id": "Glint-blade", "t": 9.5, "p": (515, 1100), "r": 20, "peak_s": 1.20, "peak_o": 0.95},
            {"id": "Glint-hilt", "t": 15.0, "p": (515, 858), "r": 18, "peak_s": 1.10, "peak_o": 0.85},
        ],
        "markers": [
            (1.0, "Камера: наезд 1", "green"), (4.0, "Камера: замер 1", "gray"),
            (6.0, "Камера: наезд 2", "green"), (8.5, "Камера: замер 2", "gray"),
            (10.5, "Камера: отъезд", "blue"), (17.5, "Камера: стоп", "gray"),
            (5.0, "Блик: корона", "yellow"), (9.5, "Блик: клинок", "yellow"),
            (15.0, "Блик: гарда", "yellow"),
        ],
    },
}

# z-order inside camera: glow -> character(+glints). UI goes outside camera (static, on top).
CAMERA_PIECES = ["glow", "character"]
UI_PIECES = ["badge", "title", "subtitle", "chips"]
UI_LABELS = {"badge": "Badge", "title": "Title", "subtitle": "Subtitle", "chips": "Feature-chips"}

# glow export = node bbox (964) + blur 1000 per side = 2964 at scale 1, then sips->2048px
GLOW_EXPORT_BOUNDS = 2964.0
GLOW_PNG = 2048.0


def data_uri(path):
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def breath_keys(amp):
    times = [round(2.5 * i, 3) for i in range(9)]
    values = []
    for t in times:
        sy = 1 + amp if (int(t / 2.5) % 2 == 1) else 1.0
        values.append(f"1,{sy:g}")
    return times, values, [EIO] * (len(times) - 1)


def camera_keys(zooms):
    # 0 hold | 1-4 push to z1 | hold | 6-8.5 push to z2 | hold | 10.5-17.5 pull back | hold to 20
    t = [0, 1, 4, 6, 8.5, 10.5, 17.5, 20]
    z1, z2 = zooms[1], zooms[2]
    v = [zooms[0], zooms[0], z1, z1, z2, z2, zooms[0], zooms[0]]
    f = [LIN, EIO, LIN, EIO, LIN, EIO, LIN]
    return t, [f"{x:g},{x:g}" for x in v], f


def glint_keys(g):
    t0, rise, fall = g["t"], 0.35, 1.0
    s0 = 0.5
    op_t = [0, round(t0 - rise, 3), t0, round(t0 + fall, 3), 20]
    op_v = [0, 0, g["peak_o"], 0, 0]
    op_f = [LIN, SNAP, "cubic-bezier(0.6,0.05,0.4,0.95)", LIN]
    sc_t = [0, round(t0 - rise, 3), t0, round(t0 + fall, 3), 19.9, 20]
    sc_v = [s0, s0, 1.0, g["peak_s"], g["peak_s"], s0]
    sc_f = [LIN, SNAP, SOFT, LIN, LIN]
    return (op_t, op_v, op_f), (sc_t, sc_v, sc_f)


def star_path(r):
    k = r * 0.28
    return (f"M0,{-r} C{k},{-k} {k},{-k} {r},0 "
            f"C{k},{k} {k},{k} 0,{r} "
            f"C{-k},{k} {-k},{k} {-r},0 "
            f"C{-k},{-k} {-k},{-k} 0,{-r} Z")


def fmt(xs):
    return ";".join(f"{x:g}" if isinstance(x, float) else str(x) for x in xs)


def anim(tag, atype, times, values, funcs):
    extra = f' type="{atype}"' if atype else ""
    return (f'<ks:animate attribute="{tag}"{extra} abs-key-times="{fmt(times)}" '
            f'values="{fmt(values)}" timing-functions="{fmt(funcs)}" repeat-end="indefinite"/>')


def build_document(label):
    spec = FILES[label]
    meta = json.loads((ASSETS / "meta.json").read_text())
    pieces = {p["key"]: p for p in meta["pieces"].values() if p["frame"] == label}
    fx, fy = spec["camera_focus"]
    bx, by = spec["breath_pivot"]
    vw, vh = spec["vw"], spec["vh"]

    img = {}
    for key in set(CAMERA_PIECES + UI_PIECES):
        img[key] = data_uri(ASSETS / label / f"{key}.png")

    # glow placement: exported png covers node bbox + 1000px blur per side
    g = pieces["glow"]
    gcx, gcy = g["x"] + g["w"] / 2, g["y"] + g["h"] / 2
    glow_size = GLOW_EXPORT_BOUNDS
    glow_x, glow_y = gcx - glow_size / 2, gcy - glow_size / 2

    bt, bv, bf = breath_keys(spec["breath_amp"])
    ct, cv, cf = camera_keys(spec["camera_zoom"])

    out = []
    out.append('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
    out.append("<!-- Created for Keyshape: AG-60517 In-App Event -->")
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:ks="http://ns.keyshapeapp.com" '
               f'viewBox="0 0 {vw} {vh}" '
               f'ks:preview="svg/css" ks:fps="60" ks:playRangeIn="0" '
               f'ks:playRangeOut="{int(LOOP * 1000)}" ks:version="1.1" style="white-space: pre;">')
    out.append(f'    <title>{spec["title"]}</title>')
    out.append(f'    <ks:export filename="{spec["export"]}" format="svg" animation="css" loop-count="0"/>')
    for t, name, color in spec["markers"]:
        out.append(f'    <ks:timemarker name="{name}" time="{t:g}" color="{color}"/>')
    out.append('    <defs>')
    out.append('        <radialGradient id="GlintGrad">'
               '<stop offset="0" stop-color="#ffffff" stop-opacity="1"/>'
               '<stop offset="0.45" stop-color="#ffffff" stop-opacity="0.85"/>'
               '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/>'
               '</radialGradient>')
    out.append(f'        <clipPath id="ksclip"><rect width="{vw}" height="{vh}"/></clipPath>')
    out.append('    </defs>')
    out.append(f'    <rect width="{vw}" height="{vh}" fill="#000000"/>')
    out.append('    <g clip-path="url(#ksclip)">')

    # --- camera rig (zoom around focus point) ---
    out.append(f'        <g id="Camera" transform="translate({fx:g},{fy:g})">')
    out.append("            " + anim("transform", "scale", ct, cv, cf))
    out.append(f'            <g transform="translate({-fx:g},{-fy:g})">')

    # glow (breathing opacity)
    out.append('                <g id="Glow">')
    out.append("                    " + anim("opacity", None, bt,
                                           ["0.82" if i % 2 == 0 else "1" for i in range(len(bt))], bf))
    out.append(f'                    <image href="{img["glow"]}" x="{glow_x:g}" y="{glow_y:g}" '
               f'width="{glow_size:g}" height="{glow_size:g}"/>')
    out.append('                </g>')

    # character breathing rig
    out.append(f'                <g id="Agnar-breathing" transform="translate({bx:g},{by:g})">')
    out.append("                    " + anim("transform", "scale", bt, bv, bf))
    out.append(f'                    <g transform="translate({-bx:g},{-by:g})">')
    ch = pieces["character"]
    out.append(f'                        <image href="{img["character"]}" x="{ch["x"]:g}" y="{ch["y"]:g}" '
               f'width="{ch["w"]:g}" height="{ch["h"]:g}"/>')
    # glints live INSIDE the breathing rig so they track the chest motion
    for gl in spec["glints"]:
        gx, gy = gl["p"]
        (ot, ov, of_), (st, sv, sf_) = glint_keys(gl)
        out.append(f'                    <g id="{gl["id"]}" transform="translate({gx:g},{gy:g})" opacity="0">')
        out.append("                        " + anim("transform", "scale", st, sv, sf_))
        out.append("                        " + anim("opacity", None, ot, ov, of_))
        out.append(f'                        <path d="{star_path(gl["r"])}" fill="url(#GlintGrad)"/>')
        out.append(f'                        <circle r="{gl["r"] * 0.16:g}" fill="#ffffff" opacity="0.95"/>')
        out.append('                    </g>')
    out.append('                    </g>')
    out.append('                </g>')
    out.append('            </g>')
    out.append('        </g>')

    # --- static UI on top ---
    for key in UI_PIECES:
        p = pieces[key]
        out.append(f'        <g id="{UI_LABELS[key]}">')
        out.append(f'            <image href="{img[key]}" x="{p["x"]:g}" y="{p["y"]:g}" '
                   f'width="{p["w"]:g}" height="{p["h"]:g}"/>')
        out.append('        </g>')

    out.append('    </g>')
    out.append('</svg>')
    xml = "\n".join(out)

    doc_path = ROOT / spec["out"]
    with zipfile.ZipFile(doc_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("document.keyshapex", xml)
    print(f"{doc_path.name}: {doc_path.stat().st_size / 1e6:.1f} MB")
    return xml


def build_preview(label):
    """SMIL twin of the keyshape document for browser preview."""
    spec = FILES[label]
    meta = json.loads((ASSETS / "meta.json").read_text())
    pieces = {p["key"]: p for p in meta["pieces"].values() if p["frame"] == label}
    fx, fy = spec["camera_focus"]
    bx, by = spec["breath_pivot"]
    vw, vh = spec["vw"], spec["vh"]
    src = {k: f"../assets/{label}/{k}.png" for k in set(CAMERA_PIECES + UI_PIECES)}

    g = pieces["glow"]
    gcx, gcy = g["x"] + g["w"] / 2, g["y"] + g["h"] / 2
    glow_x, glow_y = gcx - GLOW_EXPORT_BOUNDS / 2, gcy - GLOW_EXPORT_BOUNDS / 2

    bt, bv, bf = breath_keys(spec["breath_amp"])
    ct, cv, cf = camera_keys(spec["camera_zoom"])
    frac = lambda ts: ";".join(f"{t / LOOP:g}" for t in ts)
    splines = lambda fs: ";".join(f.replace("cubic-bezier(", "").replace(")", "").replace(",", " ")
                                  if "bezier" in f else
                                  ("0.42 0 0.58 1" if f == EIO else "0 0 1 1") for f in fs)

    def at_scale(times, values, funcs):
        return (f'<animateTransform attributeName="transform" type="scale" additive="sum" '
                f'calcMode="spline" values="{fmt(values)}" keyTimes="{frac(times)}" '
                f'keySplines="{splines(funcs)}" dur="{LOOP:g}s" repeatCount="indefinite"/>')

    def at_op(times, values, funcs):
        return (f'<animate attributeName="opacity" calcMode="spline" values="{fmt(values)}" '
                f'keyTimes="{frac(times)}" keySplines="{splines(funcs)}" '
                f'dur="{LOOP:g}s" repeatCount="indefinite"/>')

    o = []
    o.append('<?xml version="1.0" encoding="UTF-8"?>')
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}" '
             f'width="100%" height="100%">')
    o.append(f'    <title>{spec["title"]} (SMIL preview)</title>')
    o.append('    <defs><radialGradient id="GlintGrad">'
             '<stop offset="0" stop-color="#ffffff" stop-opacity="1"/>'
             '<stop offset="0.45" stop-color="#ffffff" stop-opacity="0.85"/>'
             '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient>'
             f'<clipPath id="ksclip"><rect width="{vw}" height="{vh}"/></clipPath></defs>')
    o.append(f'    <rect width="{vw}" height="{vh}" fill="#000000"/>')
    o.append('    <g clip-path="url(#ksclip)">')
    o.append(f'        <g transform="translate({fx:g},{fy:g})">')
    o.append("            " + at_scale(ct, cv, cf))
    o.append(f'            <g transform="translate({-fx:g},{-fy:g})">')
    o.append('                <g>')
    o.append("                    " + at_op(bt, ["0.82" if i % 2 == 0 else "1" for i in range(9)], bf))
    o.append(f'                    <image href="{src["glow"]}" x="{glow_x:g}" y="{glow_y:g}" '
             f'width="{GLOW_EXPORT_BOUNDS:g}" height="{GLOW_EXPORT_BOUNDS:g}"/>')
    o.append('                </g>')
    o.append(f'                <g transform="translate({bx:g},{by:g})">')
    o.append("                    " + at_scale(bt, bv, bf))
    o.append(f'                    <g transform="translate({-bx:g},{-by:g})">')
    ch = pieces["character"]
    o.append(f'                        <image href="{src["character"]}" x="{ch["x"]:g}" y="{ch["y"]:g}" '
             f'width="{ch["w"]:g}" height="{ch["h"]:g}"/>')
    for gl in spec["glints"]:
        gx, gy = gl["p"]
        (ot, ov, of_), (st, sv, sf_) = glint_keys(gl)
        o.append(f'                    <g transform="translate({gx:g},{gy:g})" opacity="0">')
        o.append("                        " + at_scale(st, sv, sf_))
        o.append("                        " + at_op(ot, ov, of_))
        o.append(f'                        <path d="{star_path(gl["r"])}" fill="url(#GlintGrad)"/>')
        o.append(f'                        <circle r="{gl["r"] * 0.16:g}" fill="#ffffff" opacity="0.95"/>')
        o.append('                    </g>')
    o.append('                    </g>')
    o.append('                </g>')
    o.append('            </g>')
    o.append('        </g>')
    for key in UI_PIECES:
        p = pieces[key]
        o.append(f'        <image href="{src[key]}" x="{p["x"]:g}" y="{p["y"]:g}" '
                 f'width="{p["w"]:g}" height="{p["h"]:g}"/>')
    o.append('    </g>')
    o.append('</svg>')
    PREVIEWS.mkdir(exist_ok=True)
    p = PREVIEWS / spec["preview"]
    p.write_text("\n".join(o))
    print(f"previews/{p.name}: {p.stat().st_size / 1024:.0f} KB")


def build_index():
    rows = []
    frame_geo = {"16x9": (960, 540), "9x16": (420, 747)}
    for label in ("16x9", "9x16"):
        s = FILES[label]
        fw, fh = frame_geo[label]
        rows.append(f"""
  <section>
    <h2>{'Event Card 16:9' if label == '16x9' else 'Event Details 9:16'}</h2>
    <iframe src="previews/{s['preview']}" title="{s['title']} preview" width="{fw}" height="{fh}"
            style="border:0;border-radius:12px;background:#000;display:block;max-width:100%"></iframe>
    <p><a class="btn" href="{s['out']}" download>Скачать {s['out']}</a></p>
  </section>""")
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AG-60517 · AdGuard v5 is here — Keyshape анимации</title>
<style>
 body{{background:#0b0d0c;color:#e8eee9;font-family:-apple-system,Helvetica,sans-serif;
      max-width:1020px;margin:0 auto;padding:32px 20px 64px}}
 h1{{font-size:28px}} h2{{font-size:20px;margin:28px 0 12px}}
 a{{color:#67b279}} .btn{{display:inline-block;background:#67b279;color:#06130a;font-weight:600;
      padding:8px 14px;border-radius:8px;text-decoration:none}}
 .note{{color:#9fb0a5;font-size:14px;line-height:1.55}}
</style></head><body>
<h1>AG-60517 · In-App Event «AdGuard v5 is here»</h1>
<p class="note">Превью ниже — браузерные SMIL-копии ключей. Рабочие файлы для Keyshape — по кнопкам
(открыть в Keyshape и анимировать руками: каналы Camera/Agnar-breathing/Glint-*/Glow уже разложены).
Цикл 20 c.</p>
{''.join(rows)}
<p class="note">Луп: наезд камеры 1.0→{FILES['16x9']['camera_zoom'][1]:g} (1–4 c) → замер →
{FILES['16x9']['camera_zoom'][1]:g}→{FILES['16x9']['camera_zoom'][2]:g} (6–8.5 c) → замер → медленный отъезд
(10.5–17.5 c). Дыхание: 5-секундный цикл, scaleY +{FILES['16x9']['breath_amp'] * 100:g}%.
Блики: корона ~5 c, меч/наплечник ~9.5 c{', гарда ~15 c' if True else ''}. UI статичен.</p>
</body></html>"""
    (ROOT / "index.html").write_text(html)
    print("index.html written")


if __name__ == "__main__":
    for label in ("16x9", "9x16"):
        build_document(label)
        build_preview(label)
    build_index()
