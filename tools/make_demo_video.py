"""Render the 30-second Onze Plek demo video from the live app.

Run:   python tools/make_demo_video.py [--lang en|nl] [--url BASE]
Needs: playwright (+ chromium), Pillow, numpy, segno, zxing-cpp, ffmpeg on PATH.
Outputs to ./demo:
  onze_plek_demo_30s_<lang>_phone.mp4   780x1688, phone screen only (drop into a phone mockup)
  onze_plek_demo_30s_<lang>_slide.mp4   1920x1080, phone + step captions + "try it" QR

Every app frame is a real screenshot of the live site, opened the way the
sticker opens it (?c=RET20507), in a fresh browser with nothing saved.
Taps are real clicks; the grey dots only show where they happen.
"""
import argparse, base64, io, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np, segno, zxingcpp
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo"
CID = "RET20507"
FPS = 30
LENGTH = 30.0
S = 2                       # device pixels per CSS px
W, H = 390, 844             # iPhone 13 screen in CSS px
SB, HI = 47, 34             # status bar and home-indicator heights
APP_H = H - SB - HI         # browser viewport height
VW, VH = W * S, H * S       # 780 x 1688 output
INK, MUTED, LINE, BG, SURFACE, ACCENT, YES = "#1C1B22", "#5B5866", "#DDD6C8", "#F4F1EA", "#FFFDF8", "#C8102E", "#1F5FA8"
FONTS = '<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">'
LOGO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 8h14l-1.5 12h-11z"/><path d="M8 8V5h8v3"/></svg>'

# Step captions on the slide version, with the second each one starts
STEPS = {
    "en": [("Scan the sticker on the container", "No app to install, no account"),
           ("See it is not full: push the flap", "Waste next to a container? It is full in fewer than 4% of cases"),
           ("Report a problem in one tap", "Ready for the city's Signalen system. No cameras, no fines"),
           ("Become the Spot Host", "One neighbour looks after this spot"),
           ("Earn the Buurtbonus together", "Clean days earn a shared reward. The block votes on it")],
    "nl": [("Scan de sticker op de container", "Geen app, geen account"),
           ("Zie dat hij niet vol is: duw de klep", "Afval naast een container? Die is in minder dan 4% van de gevallen vol"),
           ("Meld een probleem met één tik", "Klaar voor Signalen van de gemeente. Geen camera's, geen boetes"),
           ("Word Spot Host", "Eén buur zorgt voor deze plek"),
           ("Verdien samen de Buurtbonus", "Schone dagen leveren een gedeelde beloning op. De buurt kiest")],
}
TRY = {"en": ("Try it yourself", "Scan to open this container"), "nl": ("Probeer het zelf", "Scan en open deze container")}
BRAND_SUB = {"en": "Live demo · prototype", "nl": "Live demo · prototype"}
STEP_AT = [0.0, 2.7, 7.3, 11.3, 17.4]
SHEET = [round(x * FPS) for x in (1.0, 2.0, 2.6, 5.0, 8.4, 10.0, 12.2, 14.0, 16.0, 19.0, 21.5, 25.0)]
VOTE_FOR = 1   # "Fix the playground"


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def img_from_png(b, mode="RGB"):
    return Image.open(io.BytesIO(b)).convert(mode)


# ---------- static pieces rendered once with HTML ----------
def status_bar_html(fg, bg):
    return f"""<!doctype html><html><body style="margin:0;background:transparent">
<div id="sb" style="width:{W}px;height:{SB}px;box-sizing:border-box;padding:6px 26px 0 38px;display:flex;align-items:center;justify-content:space-between;
 font:600 17px -apple-system,system-ui,sans-serif;color:{fg};background:{bg}">
<span>10:30</span><span style="display:flex;gap:6px;align-items:center">
<svg width="18" height="12" viewBox="0 0 18 12" fill="currentColor"><rect x="0" y="8" width="3" height="4" rx="1"/><rect x="5" y="5.5" width="3" height="6.5" rx="1"/><rect x="10" y="3" width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/></svg>
<svg width="16" height="12" viewBox="0 0 16 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1.5 4.6a9.5 9.5 0 0 1 13 0"/><path d="M4.3 7.4a5.5 5.5 0 0 1 7.4 0"/><circle cx="8" cy="10.3" r="1.3" fill="currentColor" stroke="none"/></svg>
<svg width="27" height="13" viewBox="0 0 27 13" fill="none"><rect x=".5" y=".5" width="23" height="12" rx="3.5" stroke="currentColor" opacity=".4"/><rect x="2" y="2" width="16" height="9" rx="2" fill="currentColor"/><path d="M25 4.5v4c.8-.3 1.5-1.1 1.5-2s-.7-1.7-1.5-2z" fill="currentColor" opacity=".45"/></svg>
</span></div></body></html>"""


def home_bar(fg, bg):
    im = Image.new("RGBA", (VW, HI * S), bg)
    d = ImageDraw.Draw(im)
    bw, bh = 134 * S, 5 * S
    x0, y1 = (VW - bw) // 2, HI * S - 8 * S
    d.rounded_rectangle((x0, y1 - bh, x0 + bw, y1), radius=bh // 2, fill=fg)
    return im


def camera_html(sticker_b64):
    return f"""<!doctype html><html><body style="margin:0;width:{W}px;height:{H}px;overflow:hidden;
 background:radial-gradient(ellipse 80% 60% at 50% 45%,#6A7073 0%,#464B4E 55%,#262A2C 100%)">
<div style="position:absolute;inset:0;background:repeating-linear-gradient(90deg,rgba(255,255,255,.025) 0 2px,rgba(0,0,0,.03) 2px 5px)"></div>
<img src="data:image/png;base64,{sticker_b64}" style="position:absolute;left:50%;top:51%;width:296px;transform:translate(-50%,-50%) rotate(-2deg);
 border-radius:5px;box-shadow:0 14px 34px rgba(0,0,0,.5)">
<div style="position:absolute;inset:0;background:radial-gradient(ellipse 75% 65% at 50% 50%,transparent 60%,rgba(0,0,0,.35) 100%)"></div>
</body></html>"""


PILL_HTML = f"""<!doctype html><html><body style="margin:0;background:transparent">
<div id="pw" style="padding:20px;display:inline-block"><div style="display:inline-flex;align-items:center;gap:8px;padding:11px 18px;border-radius:999px;background:#FFD60A;color:{INK};
 font:600 16px -apple-system,system-ui,sans-serif;box-shadow:0 6px 18px rgba(0,0,0,.35)">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.8 3 2.8 15 0 18M12 3c-2.8 3-2.8 15 0 18"/></svg>
seanzlli.github.io</div></div></body></html>"""


def qr_svg(url):
    q = segno.make(url, error="q", micro=False)
    n = q.symbol_size(border=4)[0]
    svg = q.svg_inline(scale=1, border=4, dark=INK, light="#fff")
    return re.sub(r'<svg width="\d+" height="\d+"', f'<svg viewBox="0 0 {n} {n}" shape-rendering="crispEdges"', svg, count=1)


def slide_html(lang, active, url):
    rows = []
    for i, (title, sub) in enumerate(STEPS[lang]):
        state = "on" if i == active else ("done" if i < active else "")
        badge = "&#10003;" if i < active else str(i + 1)
        rows.append(f'<li class="{state}"><span class="n">{badge}</span><div><b>{title}</b><span class="sub">{sub}</span></div></li>')
    t1, t2 = TRY[lang]
    return f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>
html,body{{margin:0;width:1920px;height:1080px;background:{BG};color:{INK};font-family:'Public Sans',Arial,sans-serif}}
.wrap{{position:absolute;left:160px;top:0;width:1040px;height:1080px;display:flex;flex-direction:column;justify-content:center;gap:56px}}
.brand{{display:flex;align-items:center;gap:24px}}
.logo{{width:84px;height:84px;border-radius:24px;background:{ACCENT};color:#fff;display:grid;place-items:center;flex:none}}
.logo svg{{width:50px;height:50px}}
.brand b{{display:block;font:800 64px/1 'Public Sans',sans-serif;letter-spacing:-1px}}
.brand small{{display:block;margin-top:8px;font:600 26px/1 'Public Sans',sans-serif;color:{MUTED}}}
ol{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:20px}}
li{{display:flex;gap:24px;align-items:flex-start}}
li .n{{width:56px;height:56px;border-radius:50%;flex:none;display:grid;place-items:center;border:3px solid {LINE};box-sizing:border-box;
  font:800 26px/1 'Public Sans',sans-serif;color:{MUTED};background:{SURFACE}}}
li b{{display:block;font:700 38px/56px 'Public Sans',sans-serif;color:{MUTED}}}
li .sub{{display:block;font:600 26px/1.3 'Public Sans',sans-serif;color:{MUTED};visibility:hidden;height:34px;white-space:nowrap}}
li.done .n{{border-color:{YES};color:{YES}}}
li.on .n{{background:{ACCENT};border-color:{ACCENT};color:#fff}}
li.on b{{font-weight:800;color:{INK}}}
li.on .sub{{visibility:visible}}
.try{{display:flex;align-items:center;gap:24px}}
.try .qr{{background:#fff;border-radius:16px;padding:6px;box-shadow:0 0 0 2px {LINE}}}
.try svg{{display:block;width:150px;height:150px}}
.try b{{display:block;font:800 30px/1.2 'Public Sans',sans-serif}}
.try span{{display:block;font:600 24px/1.4 'Public Sans',sans-serif;color:{MUTED}}}
</style></head><body><div class="wrap">
<div class="brand"><span class="logo">{LOGO}</span><div><b>Onze Plek</b><small>{BRAND_SUB[lang]}</small></div></div>
<ol>{''.join(rows)}</ol>
<div class="try"><div class="qr">{qr_svg(url)}</div><div><b>{t1}</b><span>{t2}</span><span>{url.removeprefix('https://').split('?')[0].rstrip('/')}</span></div></div>
</div></body></html>"""


# phone on the slide
SCALE = 940 / VH
SCR_W, SCR_H = round(VW * SCALE), 940
BEZEL = 12
PH_W, PH_H = SCR_W + 2 * BEZEL, SCR_H + 2 * BEZEL
PH_X, PH_Y = 1920 - 160 - PH_W, (1080 - PH_H) // 2
SHADOW = 60
BEZEL_HTML = f"""<!doctype html><html><body style="margin:0;background:transparent">
<div id="ph" style="padding:{SHADOW}px;display:inline-block"><div style="width:{PH_W}px;height:{PH_H}px;border-radius:66px;background:{INK};
 box-shadow:0 28px 60px rgba(28,27,34,.28),inset 0 0 0 2px #3A3844"></div></div></body></html>"""


def rounded_mask(w, h, r):
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=r * 4, fill=255)
    return m.resize((w, h), Image.LANCZOS)


# ---------- overlays ----------
class Tap:
    def __init__(self, t0, x, y):
        self.t0, self.x, self.y = t0, x, y


def draw_taps(frame, taps, t):
    """Grey touch dot (finger down 0.25 s before the tap, lifts 0.2 s after) plus a ripple."""
    for tp in taps:
        dt = t - tp.t0
        if not -0.25 <= dt <= 0.45:
            continue
        dot = ease((dt + 0.25) / 0.1) * (1 - ease((dt - 0.2) / 0.2))
        rip = (dt / 0.4) if 0 <= dt <= 0.4 else None
        k, R = 3, 96
        ov = Image.new("RGBA", (2 * R * k, 2 * R * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        c = R * k
        if dot > 0:
            r = 30 * k * (1 - 0.08 * ease((dt + 0.25) / 0.25))
            d.ellipse((c - r, c - r, c + r, c + r), fill=(28, 27, 34, int(105 * dot)), outline=(255, 255, 255, int(200 * dot)), width=3 * k)
        if rip is not None:
            r = (34 + 50 * ease(rip)) * k
            d.ellipse((c - r, c - r, c + r, c + r), outline=(28, 27, 34, int(120 * (1 - rip))), width=4 * k)
        ov = ov.resize((2 * R, 2 * R), Image.LANCZOS)
        frame.alpha_composite(ov, (int(tp.x - R), int(tp.y - R)))
    return frame


def draw_brackets(frame, box, a, grow):
    if a <= 0:
        return frame
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    s = 1 + 0.15 * (1 - grow)
    x0, x1 = cx + (x0 - cx) * s, cx + (x1 - cx) * s
    y0, y1 = cy + (y0 - cy) * s, cy + (y1 - cy) * s
    k, pad = 3, 20
    ox, oy = int(x0 - pad), int(y0 - pad)
    w, h = int(x1 - x0 + 2 * pad), int(y1 - y0 + 2 * pad)
    ov = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    L, lw, col = 60 * k, 8 * k, (255, 214, 10, int(255 * a))
    X0, Y0, X1, Y1 = (x0 - ox) * k, (y0 - oy) * k, (x1 - ox) * k, (y1 - oy) * k
    for (px, py, dx, dy) in [(X0, Y0, 1, 1), (X1, Y0, -1, 1), (X0, Y1, 1, -1), (X1, Y1, -1, -1)]:
        d.line([(px, py + dy * L), (px, py), (px + dx * L, py)], fill=col, width=lw, joint="curve")
        for q in [(px, py + dy * L), (px + dx * L, py), (px, py)]:
            d.ellipse((q[0] - lw / 2, q[1] - lw / 2, q[0] + lw / 2, q[1] + lw / 2), fill=col)
    frame.alpha_composite(ov.resize((w, h), Image.LANCZOS), (ox, oy))
    return frame


# ---------- output ----------
def encoder(path, w, h):
    return subprocess.Popen(
        [shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
         "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=lanczos,format=yuv420p",
         "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high",
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-movflags", "+faststart", str(path)],
        stdin=subprocess.PIPE)


class Film:
    def __init__(self, lang, slides, bezel, phone_path, slide_path):
        self.n, self.taps, self.lang = 0, [], lang
        self.slides, self.bezel = slides, bezel
        self.mask = rounded_mask(SCR_W, SCR_H, 52)
        self.phone = encoder(phone_path, VW, VH)
        self.slide = encoder(slide_path, 1920, 1080)
        self.keys = {}

    @property
    def t(self):
        return self.n / FPS

    def step_bg(self, t):
        i = max(j for j, s in enumerate(STEP_AT) if t >= s)
        a = ease((t - STEP_AT[i]) / 0.35) if i > 0 else 1.0
        return self.slides[i] if a >= 1 else Image.blend(self.slides[i - 1], self.slides[i], a)

    def emit(self, screen, overlay=None):
        t = self.t
        fr = screen.convert("RGBA")
        if overlay:
            fr = overlay(fr, t)
        fr = draw_taps(fr, self.taps, t).convert("RGB")
        self.phone.stdin.write(fr.tobytes())
        sl = self.step_bg(t).copy()
        sl.paste(self.bezel, (PH_X - SHADOW, PH_Y - SHADOW), self.bezel)
        sl.paste(fr.resize((SCR_W, SCR_H), Image.LANCZOS), (PH_X + BEZEL, PH_Y + BEZEL), self.mask)
        self.slide.stdin.write(sl.tobytes())
        if self.n in SHEET:
            self.keys[self.n] = fr.resize((260, 563), Image.LANCZOS)  # for the contact sheet
        self.n += 1

    def hold(self, until, screen, overlay=None):
        while self.t < until - 1e-6:
            self.emit(screen, overlay)

    def fade(self, a_img, b_img, dur):
        n = max(1, round(dur * FPS))
        for i in range(n):
            self.emit(Image.blend(a_img, b_img, ease((i + 1) / n)))

    def close(self):
        for p in (self.phone, self.slide):
            p.stdin.close()
            p.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en", choices=["en", "nl"])
    ap.add_argument("--url", default="https://seanzlli.github.io/plek-zuidoost/")
    args = ap.parse_args()
    lang, base = args.lang, args.url
    if not base.endswith("/"):
        base += "/"
    sticker_url = f"{base}?c={CID}"
    app_url = sticker_url + ("&lang=nl" if lang == "nl" else "")
    OUT.mkdir(exist_ok=True)
    phone_path = OUT / f"onze_plek_demo_30s_{lang}_phone.mp4"
    slide_path = OUT / f"onze_plek_demo_30s_{lang}_slide.mp4"

    with sync_playwright() as p:
        b = p.chromium.launch()
        # --- static pieces
        sp = b.new_page(device_scale_factor=S)
        sp.set_content(status_bar_html(INK, SURFACE)); sb_app = img_from_png(sp.locator("#sb").screenshot(), "RGBA")
        sp.set_content(status_bar_html("#fff", "transparent")); sb_cam = img_from_png(sp.locator("#sb").screenshot(omit_background=True), "RGBA")
        sp.set_content(PILL_HTML); pill = img_from_png(sp.locator("#pw").screenshot(omit_background=True), "RGBA")
        sp.close()
        st_png = (ROOT / "qr" / f"sticker_{CID}_A6.png").read_bytes()
        cp = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=4)
        cp.set_content(camera_html(base64.b64encode(st_png).decode()), wait_until="load")
        cam = img_from_png(cp.screenshot())  # 1560 x 3376
        cp.close()
        z = zxingcpp.read_barcodes(np.array(cam))
        assert z and z[0].text == sticker_url, f"camera scene QR does not decode to the sticker URL: {z and z[0].text}"
        pos = z[0].position
        qx = [pos.top_left.x, pos.top_right.x, pos.bottom_left.x, pos.bottom_right.x]
        qy = [pos.top_left.y, pos.top_right.y, pos.bottom_left.y, pos.bottom_right.y]
        qbox = (min(qx), min(qy), max(qx), max(qy))
        slides = []
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for i in range(len(STEPS[lang])):
            pg.set_content(slide_html(lang, i, sticker_url), wait_until="networkidle"); pg.evaluate("document.fonts.ready")
            slides.append(img_from_png(pg.screenshot()))
        zs = zxingcpp.read_barcodes(np.array(slides[0]))
        assert zs and zs[0].text == sticker_url, "slide QR does not decode"
        pg.set_content(BEZEL_HTML); bezel = img_from_png(pg.locator("#ph").screenshot(omit_background=True), "RGBA")
        pg.close()

        # --- the app, opened like the sticker opens it
        dev = dict(p.devices["iPhone 13"]); dev.pop("default_browser_type", None)
        dev.update(viewport={"width": W, "height": APP_H}, device_scale_factor=S)
        ctx = b.new_context(**dev, color_scheme="light", reduced_motion="reduce", locale="en-GB" if lang == "en" else "nl-NL")
        app = ctx.new_page()
        errors = []
        app.on("pageerror", lambda e: errors.append(str(e)))
        app.goto(app_url, wait_until="networkidle")
        app.evaluate("document.fonts.ready"); app.wait_for_timeout(600)
        home = home_bar(INK, SURFACE)

        def shot():
            s = img_from_png(app.screenshot(), "RGBA")
            fr = Image.new("RGBA", (VW, VH), SURFACE)
            fr.paste(s, (0, SB * S)); fr.alpha_composite(sb_app, (0, 0)); fr.alpha_composite(home, (0, VH - HI * S))
            return fr.convert("RGB")

        def scroll_top():
            return app.evaluate("document.getElementById('view').scrollTop")

        def max_scroll():
            return app.evaluate("(()=>{const v=document.getElementById('view');return v.scrollHeight-v.clientHeight})()")

        def scroll_to(y, dur):
            y0 = scroll_top(); y = max(0, min(y, max_scroll()))
            n = max(1, round(dur * FPS))
            if abs(y - y0) < 2:
                return shot()
            for i in range(n):
                yy = y0 + (y - y0) * ease((i + 1) / n)
                app.evaluate(f"document.getElementById('view').scrollTo({{top:{yy},behavior:'instant'}})")
                im = shot(); film.emit(im)
            return im

        def reveal(sel, dur=0.5, margin=16):
            """Scroll just enough that the last match of `sel` is fully visible above the tab bar."""
            r = app.evaluate(f"""(()=>{{const v=document.getElementById('view'),l=document.querySelectorAll({sel!r}),e=l[l.length-1];
              const a=v.getBoundingClientRect(),c=e.getBoundingClientRect();return [c.top-a.top,c.bottom-a.bottom]}})()""")
            if r[1] > -margin:
                return scroll_to(scroll_top() + r[1] + margin, dur)
            if r[0] < margin:
                return scroll_to(scroll_top() + r[0] - margin, dur)
            return shot()

        def center(sel):
            bb = app.locator(sel).bounding_box()
            return bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2

        def tap(sel, t0, before):
            """Hold `before` with the finger coming down, click at t0, return the new screen."""
            cx, cy = center(sel)
            film.taps.append(Tap(t0, cx * S, (cy + SB) * S))
            film.hold(t0, before)
            app.mouse.click(cx, cy); app.wait_for_timeout(250)
            return shot()

        film = Film(lang, slides, bezel, phone_path, slide_path)

        # 0.0 - 2.7  scan the sticker
        def cam_frame(t):
            zz = 1 + 0.10 * ease(t / 2.4)
            cx, cy = (qbox[0] + qbox[2]) / 2, (qbox[1] + qbox[3]) / 2
            cw, ch = cam.width / zz, cam.height / zz
            x0 = min(max(cx - cw / 2, 0), cam.width - cw); y0 = min(max(cy - ch / 2, 0), cam.height - ch)
            k = VW / cw
            fr = cam.resize((VW, VH), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch)).convert("RGBA")
            m = 14 * S  # scan corners sit a little outside the code
            box = ((qbox[0] - x0) * k - m, (qbox[1] - y0) * k - m, (qbox[2] - x0) * k + m, (qbox[3] - y0) * k + m)
            draw_brackets(fr, box, ease((t - 0.55) / 0.25), ease((t - 0.55) / 0.3))
            a = ease((t - 1.15) / 0.25)
            if a > 0:
                pl = pill.copy(); pl.putalpha(pl.getchannel("A").point(lambda v: int(v * a)))
                px = int((box[0] + box[2]) / 2 - pl.width / 2); py = int(box[3] + 40 * S + 24 * (1 - a))
                fr.alpha_composite(pl, (px, py))
                cam_frame.pill_center = (px + pl.width / 2, py + pl.height / 2)
            fr.alpha_composite(sb_cam, (0, 0)); fr.alpha_composite(home_bar("#FFFFFF", (0, 0, 0, 0)), (0, VH - HI * S))
            return fr
        cam_frame(2.0)  # sets the pill position for the tap
        film.taps.append(Tap(2.0, *cam_frame.pill_center))
        blank = Image.new("RGB", (VW, VH))
        film.hold(2.3, blank, overlay=lambda fr, t: cam_frame(t))
        s0 = shot()
        last_cam = cam_frame(2.3).convert("RGB")
        film.fade(last_cam, s0, 0.4)

        # 2.7 - 7.3  the container card: space left, push the flap
        film.hold(7.3, s0)
        # 7.3 - 11.3  report in one tap
        report_top = app.evaluate("(()=>{const v=document.getElementById('view'),e=document.querySelector('[data-report]').closest('.card');return e.getBoundingClientRect().top-v.getBoundingClientRect().top+v.scrollTop})()")
        im = scroll_to(report_top - 16, 0.8)
        im = tap("[data-report=r_bags]", 8.6, im)
        film.hold(8.95, im); im = reveal("#view .toast")
        film.hold(11.3, im)
        # 11.3 - 17.4  become the Spot Host, set as my spot
        im = reveal("#host")
        im = tap("#host", max(film.t + 0.35, 11.9), im)
        film.hold(film.t + 0.35, im); im = reveal("#view .toast")
        film.hold(14.6, im)
        im = reveal("#setspot")
        im = tap("#setspot", max(film.t + 0.35, 15.5), im)
        film.hold(film.t + 0.35, im); im = reveal("#setspot + .pill")
        film.hold(17.1, im)
        # 17.4 - 30  My spot: clean days, Buurtbonus, vote
        nxt = tap('#tabs a[href="#spot"]', 17.5, im)
        film.fade(im, nxt, 0.2); im = nxt
        film.hold(20.2, im)
        im = scroll_to(max_scroll(), 0.8)
        film.hold(21.9, im)
        im = tap(f'[data-vote="{VOTE_FOR}"]', 22.5, im)
        film.hold(23.0, im)
        im = scroll_to(max_scroll(), 0.5)
        film.hold(LENGTH, im)
        film.close()

        state = app.evaluate("Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('plek_')).map(k=>[k,localStorage.getItem(k)]))")
        b.close()

    assert not errors, f"page errors during recording: {errors}"
    print(f"frames: {film.n} ({film.n / FPS:.2f} s)  saved in the recording browser: {state}")
    # contact sheet for a quick visual check
    sheet = Image.new("RGB", (6 * 260, 2 * 563), "white")
    for i, k in enumerate(SHEET):
        sheet.paste(film.keys[k], ((i % 6) * 260, (i // 6) * 563))
    sheet.save(OUT / f"_contact_{lang}.png")
    for f in (phone_path, slide_path):
        print(f"{f.relative_to(ROOT)}  {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
