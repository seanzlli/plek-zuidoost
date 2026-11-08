"""Make the Onze Plek QR assets and verify them by decoding.

Needs: playwright (+ chromium), segno, Pillow, opencv-python-headless,
zxing-cpp, pymupdf.   Run:  python tools/make_qr.py
Outputs to ./qr :
  qr_slide.png                 1920x1080, links to the app
  sticker_RET20507_A6.png      A6 at 300 dpi (1240x1748), links to ?c=RET20507
  sticker_RET20507_A6.pdf      A6 vector PDF, same content
"""
import re, sys
from pathlib import Path
import segno, cv2, zxingcpp, pymupdf
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = "https://seanzlli.github.io/plek-zuidoost/"
CID = "RET20507"
STICKER_URL = f"{BASE}?c={CID}"
OUT = Path(__file__).resolve().parent.parent / "qr"
OUT.mkdir(exist_ok=True)

FONTS = '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet">'
# Same icons as the app's tab bar (index.html TAB_ICON)
ICON = {
    "bin": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 8h16l-1.5 12h-13z"/><path d="M8 8V5h8v3"/></svg>',
    "bulky": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M3 11h18v6H3z"/><path d="M5 11V7h14v4M5 17v3M19 17v3"/></svg>',
    "give": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 11h16v9H4zM3 7h18v4H3zM12 7v13"/><path d="M12 7c-2-4-6-3-5 0M12 7c2-4 6-3 5 0"/></svg>',
}
LOGO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 8h14l-1.5 12h-11z"/><path d="M8 8V5h8v3"/></svg>'


def qr_svg(url, error):
    q = segno.make(url, error=error, micro=False)
    n = q.symbol_size(border=4)[0]
    svg = q.svg_inline(scale=1, border=4, dark="#000", light="#fff")
    svg = re.sub(r'<svg width="\d+" height="\d+"', f'<svg viewBox="0 0 {n} {n}" shape-rendering="crispEdges"', svg, count=1)
    return svg, q


SLIDE = f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>
html,body{{margin:0;width:1920px;height:1080px;background:#F4F1EA;color:#1C1B22;font-family:'Public Sans',Arial,sans-serif}}
.wrap{{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px}}
.qr{{background:#fff;border-radius:32px;padding:12px;box-shadow:0 0 0 2px #DDD6C8}}
.qr svg{{display:block;width:680px;height:680px}}
h1{{margin:0;font:700 92px/1 'Space Grotesk',sans-serif;letter-spacing:-1.5px;display:flex;align-items:center;gap:28px}}
h1 em{{font-style:normal;color:#C8102E}}
.logo{{width:92px;height:92px;border-radius:26px;background:#C8102E;color:#fff;display:grid;place-items:center}}
.logo svg{{width:56px;height:56px}}
.url{{margin:0;font:600 34px 'Public Sans',sans-serif;color:#5B5866;letter-spacing:.2px}}
</style></head><body><div class="wrap">
<div class="qr">%QR%</div>
<h1><span class="logo">{LOGO}</span><span>Scan to try <em>Onze Plek</em></span></h1>
<p class="url">{BASE.removeprefix('https://').rstrip('/')}</p>
</div></body></html>"""

LINES = [("bin", "Container full?", "Container vol?"),
         ("bulky", "Something big?", "Iets groots kwijt?"),
         ("give", "Give it away?", "Geef het door?")]
STICKER = f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>
@page{{size:105mm 148mm;margin:0}}
*{{box-sizing:border-box}}
html,body{{margin:0;width:105mm;height:148mm;background:#fff;color:#1C1B22;font-family:'Public Sans',Arial,sans-serif;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}}
.sheet{{width:105mm;height:148mm;padding:6mm;display:flex;flex-direction:column;gap:4mm;overflow:hidden}}
.head{{background:#C8102E;color:#fff;border-radius:4mm;padding:3.6mm 4.5mm;display:flex;align-items:center;gap:3.2mm}}
.head .logo{{width:11mm;height:11mm;border-radius:3mm;background:#fff;color:#C8102E;display:grid;place-items:center;flex:none}}
.head .logo svg{{width:7mm;height:7mm}}
.head b{{font:700 10.5mm/1 'Space Grotesk',sans-serif;letter-spacing:-.25mm}}
.qr{{align-self:center}}
.qr svg{{display:block;width:62mm;height:62mm}}
.lines{{display:flex;flex-direction:column;gap:2.6mm}}
.line{{display:flex;align-items:center;gap:2.8mm;white-space:nowrap}}
.line svg{{width:6.4mm;height:6.4mm;flex:none;color:#C8102E}}
.line b{{font:700 4.6mm/1.1 'Space Grotesk',sans-serif}}
.line span{{font:600 4.2mm/1.1 'Public Sans',sans-serif;color:#5B5866}}
.id{{margin-top:auto;border-top:.35mm solid #DDD6C8;padding-top:3mm;display:flex;justify-content:space-between;align-items:center}}
.id small{{font:600 3.1mm/1.25 'Public Sans',sans-serif;color:#5B5866}}
.id b{{font:700 7.5mm/1 'Space Grotesk',sans-serif;letter-spacing:.35mm}}
</style></head><body><div class="sheet">
<div class="head"><span class="logo">{LOGO}</span><b>Onze Plek</b></div>
<div class="qr">%QR%</div>
<div class="lines">{''.join(f'<div class="line">{ICON[i]}<b>{en}</b><span>/ {nl}</span></div>' for i, en, nl in LINES)}</div>
<div class="id"><small>Container number<br>Containernummer</small><b>{CID}</b></div>
</div></body></html>"""


def decode(img_rgb):
    """Return (opencv_result, zxing_result) for an RGB numpy image."""
    a, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR))
    z = zxingcpp.read_barcodes(img_rgb)
    return a, (z[0].text if z else "")


def verify(label, img_rgb, want):
    ok = True
    for scale in (1.0, 0.25):  # full size, and as a small/far-away phone camera would see it
        im = img_rgb if scale == 1 else np.array(Image.fromarray(img_rgb).resize(
            (int(img_rgb.shape[1] * scale), int(img_rgb.shape[0] * scale)), Image.LANCZOS))
        a, z = decode(im)
        good = a == want and z == want
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {label} @{int(scale*100)}%: opencv={a!r} zxing={z!r}")
    return ok


def main():
    slide_svg, slide_q = qr_svg(BASE, "m")
    st_svg, st_q = qr_svg(STICKER_URL, "q")
    print(f"slide QR: v{slide_q.version}-{slide_q.error}  sticker QR: v{st_q.version}-{st_q.error}")
    with sync_playwright() as p:
        b = p.chromium.launch()
        # Slide
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.set_content(SLIDE.replace("%QR%", slide_svg), wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        pg.screenshot(path=str(OUT / "qr_slide.png"))
        pg.close()
        # Sticker: 300 dpi PNG (1 CSS px = 1/96 in, so scale 300/96)
        pg = b.new_page(viewport={"width": 397, "height": 560}, device_scale_factor=300 / 96)
        pg.set_content(STICKER.replace("%QR%", st_svg), wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        wrap = pg.evaluate("[...document.querySelectorAll('.line')].map(e=>e.scrollWidth<=e.clientWidth && e.getBoundingClientRect().height<30)")
        fits = pg.evaluate("(()=>{const s=document.querySelector('.sheet');return s.scrollHeight<=s.clientHeight})()")
        print(("PASS" if all(wrap) and fits else "FAIL") + f" sticker layout: lines on one row {wrap}, content fits A6 {fits}")
        raw = OUT / "_sticker_raw.pdf"
        pg.pdf(path=str(raw), width="105mm", height="148mm", print_background=True,
               margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}, prefer_css_page_size=True)
        pg.close()
        b.close()

    # Chromium rounds the page to ~105.2 x 148.2 mm: trim the (white) right/bottom sliver to exact A6
    A6W, A6H = 105 / 25.4 * 72, 148 / 25.4 * 72
    doc = pymupdf.open(raw)
    top = doc[0].mediabox.y1  # PDF y axis points up: keep the top edge, trim at the bottom
    doc[0].set_mediabox(pymupdf.Rect(0, top - A6H, A6W, top))
    doc.save(OUT / f"sticker_{CID}_A6.pdf", garbage=3, deflate=True)
    doc.close()
    raw.unlink()

    # 300 dpi PNG rendered from that same PDF, so print PNG and PDF are identical
    sp = OUT / f"sticker_{CID}_A6.png"
    doc = pymupdf.open(OUT / f"sticker_{CID}_A6.pdf")
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(1240 / A6W, 1748 / A6H), alpha=False)
    Image.frombytes("RGB", (pix.w, pix.h), pix.samples).save(sp, dpi=(300, 300))
    doc.close()
    Image.open(OUT / "qr_slide.png").convert("RGB").save(OUT / "qr_slide.png")

    ok = True
    ok &= verify("qr_slide.png", np.array(Image.open(OUT / "qr_slide.png").convert("RGB")), BASE)
    chk = Image.open(sp)
    print(f"sticker PNG: {chk.size[0]}x{chk.size[1]} px, dpi={tuple(round(d) for d in chk.info.get('dpi', (0, 0)))}")
    ok &= verify(sp.name, np.array(chk.convert("RGB")), STICKER_URL)
    doc = pymupdf.open(OUT / f"sticker_{CID}_A6.pdf")
    w_mm, h_mm = doc[0].rect.width / 72 * 25.4, doc[0].rect.height / 72 * 25.4
    size_ok = len(doc) == 1 and abs(w_mm - 105) < 0.5 and abs(h_mm - 148) < 0.5
    ok &= size_ok
    print(f"{'PASS' if size_ok else 'FAIL'} sticker PDF: {len(doc)} page(s), {w_mm:.1f} x {h_mm:.1f} mm, fonts: {sorted({f[3] for f in doc[0].get_fonts()})}")
    pix = doc[0].get_pixmap(dpi=300)
    ok &= verify("sticker PDF (rasterised 300 dpi)", np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy(), STICKER_URL)
    print("ALL QR CHECKS PASSED" if ok else "QR CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
