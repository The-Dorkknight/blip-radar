#!/usr/bin/env python3
"""Blip — build the PDF manual that ships with every release.

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

    pip install markdown playwright pillow && python -m playwright install chromium   # once
    python3 tools/make_pdf.py                    # -> docs/Blip-manual.pdf
    python3 tools/make_pdf.py --out blip.pdf

Turns the repo's own documents (README, How it works, Design notes, hardware
guides, changelog, third-party notes, licence) into one illustrated PDF: a cover,
a contents page, one chapter per document, page numbers. Images come from
docs/images/ exactly as the README shows them; links to other repo files point at
the GitHub copy. The release workflow (.github/workflows/release.yml) runs this
and attaches the PDF to every GitHub release.
"""
import argparse
import html
import os
import pathlib
import re
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/The-Dorkknight/blip-radar"
CHAPTERS = [
    ("README.md", "Overview, setup and use"),
    ("HOW_IT_WORKS.md", "How it works"),
    ("DESIGN_NOTES.md", "Design notes and research"),
    ("hardware/wiring.md", "Wiring"),
    ("hardware/max4466-mod.md", "Stetho front end: the MAX4466 mod"),
    ("hardware/audio-out.md", "Sound out of the node"),
    ("CHANGELOG.md", "Changelog"),
    ("THIRD_PARTY.md", "Third-party notices"),
    ("LICENSE.md", "Licence"),
]

CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font: 10.2pt/1.5 "Inter", "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif; color: #17241c; margin: 0; }
a { color: #0a7d43; text-decoration: none; border-bottom: 1px dotted #7fc8a0; }
h1, h2, h3, h4 { color: #0b5d33; line-height: 1.25; break-after: avoid; }
h1 { font-size: 20pt; margin: 0 0 8pt; }
h2 { font-size: 14.5pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 2px solid #c9eed8; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; }
h4 { font-size: 10.5pt; margin: 10pt 0 3pt; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 18pt; }
code { font: 8.8pt/1.4 "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace; background: #eef7f1; padding: 0 3pt; border-radius: 3pt; }
pre { background: #f2f8f4; border: 1px solid #cfe9da; border-left: 4px solid #39c977; border-radius: 6pt; padding: 7pt 9pt; white-space: pre-wrap; word-break: break-word; font-size: 8.4pt; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
blockquote { margin: 8pt 0; padding: 6pt 10pt; background: #fff6df; border-left: 4px solid #f0b429; border-radius: 4pt; }
blockquote p { margin: 2pt 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt; break-inside: auto; }
tr { break-inside: avoid; }
th { background: #dff5e8; color: #0b5d33; text-align: left; }
th, td { border: 1px solid #cde6d7; padding: 4pt 6pt; vertical-align: top; }
tr:nth-child(even) td { background: #f7fcf9; }
img { max-width: 100%; height: auto; max-height: 150mm; display: inline-block; border-radius: 4pt; break-inside: avoid; }
td img { max-width: 34mm; max-height: 66mm; }
p > img:only-child { display: block; margin: 6pt auto; max-height: 120mm; box-shadow: 0 1pt 4pt rgba(0,0,0,.18); }
img[data-k="oled"] { max-width: 62mm; margin: 2pt 4pt; image-rendering: pixelated; box-shadow: none; }
hr { border: 0; border-top: 1px solid #cde6d7; margin: 12pt 0; }
.chapter { break-before: page; }
.chap-head { background: linear-gradient(135deg, #0f3a22 0%, #145a33 55%, #1f9c56 100%); color: #eafff2; border-radius: 10pt; padding: 14pt 16pt 12pt; margin-bottom: 12pt; }
.chap-head .kicker { font-size: 8.5pt; letter-spacing: .14em; text-transform: uppercase; color: #9dffc6; }
.chap-head h1 { color: #ffffff; margin: 2pt 0 2pt; font-size: 21pt; }
.chap-head .src { font-size: 8.5pt; color: #bde9cf; margin: 0; }
.cover { height: 255mm; display: flex; flex-direction: column; justify-content: space-between; }
.cover .top { background: radial-gradient(ellipse at 50% 120%, #1f9c56 0%, #0f3a22 55%, #06120b 100%); color: #eafff2; border-radius: 14pt; padding: 22pt 22pt 18pt; }
.cover .brand { display: flex; align-items: center; gap: 14pt; }
.cover .brand img { width: 62pt; height: 62pt; border-radius: 14pt; box-shadow: 0 0 18pt rgba(57,255,138,.45); }
.cover h1 { color: #39ff8a; font-size: 44pt; letter-spacing: .08em; margin: 0; text-shadow: 0 0 14pt rgba(57,255,138,.5); }
.cover .tag { font-size: 13pt; color: #d9f5e3; margin: 6pt 0 0; }
.cover .wip { display: inline-block; margin-top: 12pt; background: #ffd34d; color: #3a2a00; font-weight: 700; font-size: 9pt; padding: 3pt 9pt; border-radius: 20pt; }
.cover .meta { margin-top: 10pt; font-size: 9.5pt; color: #bde9cf; }
.cover .shots { display: flex; gap: 8pt; justify-content: center; align-items: flex-start; margin: 14pt 0; }
.cover .shots img { max-height: 118mm; width: auto; max-width: 31%; border-radius: 8pt; box-shadow: 0 2pt 10pt rgba(0,0,0,.25); }
.cover .note { font-size: 8.5pt; color: #4b6b58; border-top: 1px solid #cde6d7; padding-top: 6pt; }
.toc { break-before: page; }
.toc ol { list-style: none; padding: 0; counter-reset: ch; }
.toc li { counter-increment: ch; display: flex; gap: 10pt; align-items: baseline; padding: 7pt 0; border-bottom: 1px dashed #cde6d7; font-size: 11.5pt; }
.toc li::before { content: counter(ch); font-weight: 700; color: #ffffff; background: #1f9c56; border-radius: 50%; width: 18pt; height: 18pt; font-size: 9pt; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.toc li span { margin-left: auto; color: #6b8a77; font-size: 8.5pt; }
"""


def version():
    m = re.search(r'#define BLIP_VERSION "([^"]+)"', (ROOT / "firmware/include/config.h").read_text(encoding="utf-8"))
    return m.group(1) if m else "unknown"


_SHRUNK = {}


def img_uri(p, tmp):
    """A print-sized copy of an image (max 1100 px wide, JPEG for photos/screens) so the PDF stays small.
    Falls back to the original if Pillow isn't installed."""
    key = str(p)
    if key in _SHRUNK:
        return _SHRUNK[key]
    uri = p.as_uri()
    try:
        from PIL import Image
        im = Image.open(p)
        pixel_art = p.name.startswith("oled-")
        if not pixel_art and p.suffix.lower() != ".svg":
            if im.width > 1100:
                im = im.resize((1100, round(im.height * 1100 / im.width)), Image.LANCZOS)
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, "white")
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[3])
                im = bg
            out = pathlib.Path(tmp) / ("img%d.jpg" % len(_SHRUNK))
            im.convert("RGB").save(out, quality=84, optimize=True)
            uri = out.as_uri()
    except Exception:
        pass
    _SHRUNK[key] = uri
    return uri


def chapter_html(idx, rel, md_mod, tmp):
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    body = md_mod.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc", "attr_list"],
                           extension_configs={"toc": {"permalink": False}})
    first_h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    if first_h1:
        body = body[:first_h1.start()] + body[first_h1.end():]
    docdir = path.parent
    index = {r: i for i, (r, _) in enumerate(CHAPTERS, 1)}

    def fix_src(m):
        src = html.unescape(m.group(2))
        if re.match(r"https?:", src):
            return ""                                      # badges etc.: don't fetch the internet for a manual
        p = (docdir / src).resolve()
        if not p.exists():
            return ""
        return '%s="%s"%s' % (m.group(1), img_uri(p, tmp), ' data-k="oled"' if p.name.startswith("oled-") else "")
    body = re.sub(r'(src)="([^"]+)"', fix_src, body)
    body = re.sub(r"<img(?![^>]*\ssrc=)[^>]*>", "", body)          # images whose file doesn't exist

    def fix_href(m):
        href = html.unescape(m.group(1))
        if re.match(r"(https?:|mailto:)", href):
            return 'href="%s"' % html.escape(href)
        if href.startswith("#"):
            return 'href="#ch%d-%s"' % (idx, href[1:])
        target, _, frag = href.partition("#")
        tp = (docdir / target).resolve()
        try:
            trel = tp.relative_to(ROOT).as_posix()
        except ValueError:
            return 'href="%s"' % html.escape(href)
        if trel in index:
            return 'href="#ch%d%s"' % (index[trel], "-" + frag if frag else "")
        kind = "tree" if tp.is_dir() else "blob"
        return 'href="%s/%s/main/%s"' % (REPO_URL, kind, trel)
    body = re.sub(r'href="([^"]*)"', fix_href, body)
    body = re.sub(r'\sid="([^"]+)"', lambda m: ' id="ch%d-%s"' % (idx, m.group(1)), body)
    return body


def build_html(ver, tmp):
    import markdown
    icon = (ROOT / "docs/images/icon-512.png").as_uri()
    shots = "".join('<img src="%s">' % img_uri(ROOT / "docs/images" / f, tmp)
                    for f in ("ui-scope.webp", "ui-stetho.webp") if (ROOT / "docs/images" / f).exists())
    toc = "".join('<li><a href="#ch%d">%s</a><span>%s</span></li>' % (i, html.escape(t), html.escape(r))
                  for i, (r, t) in enumerate(CHAPTERS, 1) if (ROOT / r).exists())
    parts = ["""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Blip %(v)s manual</title><style>%(css)s</style></head><body>
<section class="cover">
  <div class="top">
    <div class="brand"><img src="%(icon)s"><div><h1>BLIP</h1><p class="tag">One small ESP32, one 24 GHz radar, and an old phone as the screen.</p></div></div>
    <span class="wip">WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN</span>
    <div class="meta">Manual and research notes · version %(v)s · %(date)s<br>%(url)s</div>
  </div>
  <div class="shots">%(shots)s</div>
  <div class="note">Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight). Licensed under the PolyForm Noncommercial License 1.0.0 —
  source-available, free for non-commercial use. Provided as-is with no warranty and no liability. <b>Not a medical device.</b>
  Screenshots are from the simulator, not a real radar. This PDF is generated from the repository's own documents by tools/make_pdf.py.</div>
</section>
<section class="toc"><h1>Contents</h1><ol>%(toc)s</ol></section>
""" % {"v": html.escape(ver), "css": CSS, "icon": icon, "date": time.strftime("%Y-%m-%d"), "url": REPO_URL, "shots": shots, "toc": toc}]
    for i, (rel, title) in enumerate(CHAPTERS, 1):
        if not (ROOT / rel).exists():
            continue
        parts.append('<section class="chapter" id="ch%d"><div class="chap-head"><div class="kicker">Chapter %d</div><h1>%s</h1><p class="src">%s</p></div>%s</section>'
                     % (i, i, html.escape(title), html.escape(rel), chapter_html(i, rel, markdown, tmp)))
    parts.append("</body></html>")
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Build the Blip PDF manual")
    ap.add_argument("--out", default=str(ROOT / "docs" / "Blip-manual.pdf"))
    ap.add_argument("--html", help="also keep the intermediate HTML here")
    a = ap.parse_args()
    try:
        import markdown  # noqa: F401
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        print("Needs: pip install markdown playwright && python -m playwright install chromium  (%s)" % e)
        return 2
    ver = version()
    with tempfile.TemporaryDirectory() as td:
        doc = build_html(ver, td)
        hp = pathlib.Path(a.html) if a.html else pathlib.Path(td) / "manual.html"
        hp.write_text(doc, encoding="utf-8")
        foot = ('<div style="width:100%%;font:7.5pt system-ui,sans-serif;color:#6b8a77;padding:0 15mm;display:flex;justify-content:space-between">'
                '<span>Blip %s · work in progress · source-available, non-commercial</span>'
                '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>') % html.escape(ver)
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-proxy-server", "--allow-file-access-from-files"])
            page = b.new_page()
            page.goto(hp.as_uri(), wait_until="load")
            page.wait_for_timeout(300)
            page.pdf(path=a.out, format="A4", print_background=True, display_header_footer=True,
                     header_template="<span></span>", footer_template=foot,
                     margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"}, prefer_css_page_size=False)
            b.close()
    print("wrote %s (%d KB, Blip %s)" % (a.out, os.path.getsize(a.out) // 1024, ver))
    return 0


if __name__ == "__main__":
    sys.exit(main())
