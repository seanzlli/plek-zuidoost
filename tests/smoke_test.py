"""Smoke test for Onze Plek (index.html) at phone size.

Usage:  python3 tests/smoke_test.py [base_url]      (ENGINE=webkit for Safari's engine)
Without base_url it serves the repo folder on a local port.
Writes screenshots to ./screenshots and exits non-zero on any failure.
"""
import functools, http.server, json, os, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
OUT.mkdir(exist_ok=True)
W, H = 375, 812
TABS = ["bin", "bulky", "give", "spot", "radar"]
LANGS = ["en", "nl"]
failures, log = [], []


def check(cond, msg):
    (log if cond else failures).append(("PASS " if cond else "FAIL ") + msg)


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/"


OVERFLOW_JS = """() => {
  const W = document.documentElement.clientWidth, main = document.getElementById('view');
  const out = {W, doc: document.documentElement.scrollWidth, main: main.scrollWidth, mainClient: main.clientWidth, offenders: [], scrollers: []};
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect(); if (!r.width) continue;
    if (el.closest('.leaflet-container')) continue; // map tiles are clipped by the map box
    const wrap = el.closest('[style*="overflow-x:auto"]');
    if (!wrap && (r.right > W + 0.5 || r.left < -0.5))
      out.offenders.push(el.tagName.toLowerCase() + (el.className ? '.' + el.className : '') + ' right=' + Math.round(r.right));
  }
  for (const card of document.querySelectorAll('.card')) {
    const q = card.getBoundingClientRect();
    for (const el of card.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width && r.right > q.right + 0.5 && !el.closest('[style*="overflow-x:auto"]') && !el.closest('.leaflet-container'))
        out.offenders.push('outside its card: ' + el.tagName.toLowerCase() + (el.className ? '.' + el.className : ''));
    }
  }
  for (const el of document.querySelectorAll('[style*="overflow-x:auto"]'))
    if (el.scrollWidth > el.clientWidth + 1) out.scrollers.push(el.scrollWidth + '>' + el.clientWidth);
  return out;
}"""


def new_page(browser, lang, extra_storage=None, **ctx_opts):
    ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=2, **ctx_opts)
    storage = {"plek_lang": json.dumps(lang), **(extra_storage or {})}
    ctx.add_init_script("(" + "s => { for (const k in s) localStorage.setItem(k, s[k]); }" + f")({json.dumps(storage)})")
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append("console." + m.type + ": " + m.text) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
    page.on("requestfailed", lambda r: errs.append("requestfailed: " + r.url))
    return ctx, page, errs


def settle(page):
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")


def shoot(page, name, full=False):
    page.wait_for_timeout(400)  # let map tiles finish their fade-in
    if full:
        h = page.evaluate("document.querySelector('header').offsetHeight + document.getElementById('view').scrollHeight + document.getElementById('tabs').offsetHeight")
        page.set_viewport_size({"width": W, "height": max(H, h)})
    page.screenshot(path=str(OUT / f"{name}.png"))
    if full:
        page.set_viewport_size({"width": W, "height": H})


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else serve()
    if not base.endswith("/"):
        base += "/"
    print("Testing", base)
    with sync_playwright() as p:
        browser = getattr(p, os.environ.get("ENGINE", "chromium")).launch()
        print("Engine:", os.environ.get("ENGINE", "chromium"))

        # 1. Every tab, both languages, light + dark: screenshots + overflow + console
        for scheme, lang in [("light", "en"), ("light", "nl"), ("dark", "en"), ("dark", "nl")]:
            for tab in TABS:
                extra = {"plek_spot": json.dumps("RET20507")} if tab == "spot" else None
                ctx, page, errs = new_page(browser, lang, extra, color_scheme=scheme)
                page.goto(base + "#" + tab)
                settle(page)
                if tab == "bin":
                    check(page.evaluate("!!window.L") and page.is_visible(".lmap"), f"{scheme}/{lang}/bin: live map loaded (Leaflet + SRI ok)")
                    page.wait_for_function("document.querySelectorAll('.lmap .leaflet-tile-loaded').length > 0", timeout=15000)
                    check(page.evaluate("document.querySelectorAll('.lmap path.bin').length") == 1206, f"{scheme}/{lang}/bin: 1,206 containers on the map")
                tag = lang if scheme == "light" else f"dark_{lang}"
                cur = page.get_attribute("nav a[aria-current=page]", "href")
                check(cur == "#" + tab, f"{tag}/{tab}: tab is active ({cur})")
                check(page.evaluate("document.documentElement.lang") == lang, f"{tag}/{tab}: html lang={lang}")
                o = page.evaluate(OVERFLOW_JS)
                check(o["doc"] <= o["W"] and o["main"] <= o["mainClient"] and not o["offenders"],
                      f"{tag}/{tab}: no horizontal overflow (doc {o['doc']}/{o['W']}, main {o['main']}/{o['mainClient']}, offenders {o['offenders'][:3]})")
                if o["scrollers"]:
                    log.append(f"NOTE {tag}/{tab}: inner horizontal scroller(s) {o['scrollers']}")
                shoot(page, f"{tag}_{tab}")
                shoot(page, f"{tag}_{tab}_full", full=True)
                check(not errs, f"{tag}/{tab}: no console errors {errs}")
                ctx.close()

        # 2. Copy checks
        text = (ROOT / "index.html").read_text(encoding="utf-8") if base.startswith("http://127.0.0.1") else None
        ctx, page, errs = new_page(browser, "en")
        page.goto(base)
        settle(page)
        html = page.content()
        for bad in ["Containers are full less than", "minder dan 4% van de tijd", "image detection", "beeldherkenning",
                    "Pickup point (street)", "Ophaalpunt (straat)", "Unclaimed items are collected"]:
            check(bad not in html and (text is None or bad not in text), f"old copy gone: {bad!r}")
        ctx.close()

        # 3. Bulky flow: Geef door hint, and pickup dates start after the 48 h window for usable items
        DAY_JS = """([off, lang]) => { const x = new Date(); x.setDate(x.getDate() + off);
          return x.toLocaleDateString(lang === 'nl' ? 'nl-NL' : 'en-GB', {weekday:'long', day:'numeric', month:'long'}); }"""
        for lang in LANGS:
            for usable, first_day in (("1", 3), ("0", 1)):
                ctx, page, errs = new_page(browser, lang)
                page.goto(base + "#bulky")
                settle(page)
                page.click("[data-item='0']")
                page.click(f"[data-usable='{usable}']")
                dates = page.eval_on_selector_all("[data-date]", "els => els.map(e => e.dataset.date)")
                want_dates = [page.evaluate(DAY_JS, [first_day + i, lang]) for i in range(3)]
                check(dates == want_dates, f"{lang}/bulky usable={usable}: pickup dates start today+{first_day} {dates}")
                if usable == "1":
                    want = "keep it inside" if lang == "en" else "houd het binnen"
                    check(want in page.inner_text("#view"), f"{lang}/bulky: Geef door hint says {want!r}")
                    shoot(page, f"{lang}_bulky_flow_full", full=True)
                check(not errs, f"{lang}/bulky flow: no console errors {errs}")
                ctx.close()

        # 3b. "Use my location": found nearby, blocked, and far away
        near_pt = {"latitude": 52.3218, "longitude": 4.9562}
        NEAREST_JS = """([la, lo]) => { let best = null, bd = Infinity;
          for (const o of BINS) { const d = dist({lat: la, lon: lo}, o); if (d < bd) { bd = d; best = o; } } return [best.id, Math.round(bd)]; }"""
        for lang in LANGS:
            ctx, page, errs = new_page(browser, lang, geolocation=near_pt, permissions=["geolocation"])
            page.goto(base)
            settle(page)
            page.click("#locate")
            page.wait_for_selector(".lmap path.me", timeout=15000)
            settle(page)
            nid, nd = page.evaluate(NEAREST_JS, [near_pt["latitude"], near_pt["longitude"]])
            body = page.inner_text("#view")
            want = (f"nearest container ({nd}\u00a0m)" if lang == "en" else f"dichtstbijzijnde container ({nd}\u00a0m)")
            check(want in body and f"{nid} ·" in body, f"{lang} locate (near): blue dot shown, {nid} selected, says {want!r}")
            check(page.evaluate("LM.map.getBounds().contains([%f,%f])" % (near_pt["latitude"], near_pt["longitude"])), f"{lang} locate (near): map shows the user")
            shoot(page, f"{lang}_locate_near")
            check(not errs, f"{lang} locate (near): no console errors {errs}")
            ctx.close()
        ctx, page, errs = new_page(browser, "en")  # no permission granted -> blocked
        page.goto(base)
        settle(page)
        page.click("#locate")
        page.wait_for_function("document.getElementById('view').innerText.includes('Location is blocked')", timeout=15000)
        check(page.query_selector(".lmap path.me") is None, "locate (blocked): message shown, no dot")
        check(not errs, f"locate (blocked): no console errors {errs}")
        ctx.close()
        ctx, page, errs = new_page(browser, "en", {"plek_last": json.dumps("RET20385")},
                                   geolocation={"latitude": 52.3791, "longitude": 4.9003}, permissions=["geolocation"])  # Amsterdam Centraal
        page.goto(base)
        settle(page)
        page.click("#locate")
        page.wait_for_function("document.getElementById('view').innerText.includes('from the nearest Zuidoost container')", timeout=15000)
        check("RET20385 ·" in page.inner_text("#view") and page.query_selector(".lmap path.me") is not None,
              "locate (far, Amsterdam Centraal): dot shown, selection unchanged")
        check(not errs, f"locate (far): no console errors {errs}")
        ctx.close()

        # 4. Nearest-container wording for 'Onbekend' and 'Grof'
        for lang, words in [("en", {"Onbekend": "Nearest other container (type not listed)", "Grof": "Nearest other bulky waste point"}),
                            ("nl", {"Onbekend": "Dichtstbijzijnde andere container (type onbekend)", "Grof": "Dichtstbijzijnde andere grofafvalplek"})]:
            for kind, want in words.items():
                ctx, page, errs = new_page(browser, lang)
                page.goto(base)
                settle(page)
                cid = page.evaluate(f"BINS.find(b=>b.f==='{kind}').id")
                page.goto(base + "?c=" + cid)
                settle(page)
                body = page.inner_text("#view")
                check(want in body and "type not listed container" not in body and "voor type onbekend" not in body,
                      f"{lang}/{kind} ({cid}): nearest line reads {want!r}")
                if kind == "Onbekend":
                    shoot(page, f"{lang}_onbekend_{cid}_full", full=True)
                ctx.close()

        # 5. Deep link ?c=RET20507
        cases = [
            ("?c=RET20507", {}, "plain"),
            ("?c=ret20507", {}, "lower case"),
            ("?c=%20RET%2020507%20", {}, "spaces"),
            ("?c=RET20507#radar", {}, "with another tab in the hash"),
            ("?c=RET20507", {"plek_last": json.dumps("RET20385")}, "overrides last-viewed container"),
        ]
        for i, (q, extra, label) in enumerate(cases):
            for lang in LANGS:
                ctx, page, errs = new_page(browser, lang, extra)
                page.goto(base + q)
                settle(page)
                cur = page.get_attribute("nav a[aria-current=page]", "href")
                body = page.inner_text("#view")
                ok = cur == "#bin" and "RET20507 ·" in body and page.is_hidden("#nf")
                check(ok, f"{lang} deep link {q} ({label}): Bin tab ({cur}), shows RET20507")
                zc = page.evaluate("[LM.map.getZoom(), LM.map.getCenter().distanceTo([52.32142, 4.95545])]")
                check(zc[0] == 17 and zc[1] < 5, f"{lang} deep link {q}: map zoomed to RET20507 (zoom {zc[0]}, {zc[1]:.1f} m off)")
                check(not errs, f"{lang} deep link {q}: no console errors {errs}")
                if i == 0:
                    shoot(page, f"{lang}_deeplink_RET20507")
                    shoot(page, f"{lang}_deeplink_RET20507_full", full=True)
                ctx.close()
        ctx, page, errs = new_page(browser, "en")
        page.goto(base + "?c=NOPE123")
        settle(page)
        check(page.is_visible("#nf") and page.get_attribute("nav a[aria-current=page]", "href") == "#bin",
              "unknown ?c=NOPE123: Bin tab with 'not found' message")
        check(not errs, f"unknown ?c: no console errors {errs}")
        ctx.close()

        # 5b. Confirmations stay visible together (demo flow: report -> host -> set as my spot)
        ctx, page, errs = new_page(browser, "en")
        page.goto(base + "?c=RET20507")
        settle(page)
        page.click("[data-report='r_bags']"); page.click("#host"); page.click("#setspot")
        body = page.inner_text("#view")
        check("ready to send to the city" in body and "neighbourhood coordinator" in body and "Saved as your spot" in body
              and page.query_selector("#host") is None, "report, host and spot confirmations all stay on screen")
        check(not errs, f"confirmations: no console errors {errs}")
        ctx.close()

        # 6. Demo helpers and polish
        ctx, page, errs = new_page(browser, "nl", {"plek_taken": json.dumps(["ex0"]), "plek_spot": json.dumps("RET20507"), "plek_vote": "1"})
        page.goto(base + "?c=RET20507&reset")
        settle(page)
        left = page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('plek_'))")
        check(left == [] and page.evaluate("location.search") == "?c=RET20507" and page.evaluate("document.documentElement.lang") == "en",
              f"?reset clears saved demo state (left {left}), keeps ?c, back to English")
        page.evaluate("location.hash='#give'"); page.wait_for_timeout(300)
        check(page.locator("[data-take]").count() == 3, "after ?reset all three Geef door examples can be taken again")
        check(not errs, f"?reset: no console errors {errs}")
        ctx.close()
        ctx, page, errs = new_page(browser, "en")
        page.goto(base + "?lang=nl")
        settle(page)
        check(page.evaluate("document.documentElement.lang") == "nl" and page.evaluate("location.search") == "",
              "?lang=nl opens in Dutch and cleans the URL")
        page.evaluate("location.hash='#radar'"); page.wait_for_timeout(300)
        kp = page.inner_text(".kpis")
        check("34,5%" in kp and "42,4%" in kp and "34.5" not in kp, f"NL numbers use a decimal comma: {kp.split(chr(10))[:6]}")
        ctx.close()
        for lang in LANGS:
            ctx, page, errs = new_page(browser, lang)
            page.goto(base + "?c=RET20507")
            settle(page)
            top = page.evaluate("document.getElementById('bincard').getBoundingClientRect().top")
            check(0 <= top < 200, f"{lang} scan of sticker: container card is on the first screen (top={top:.0f}px)")
            shoot(page, f"{lang}_scan_first_screen")
            ctx.close()
        ctx, page, errs = new_page(browser, "en", {"plek_posts": json.dumps([{"title": "Old chair", "k": "Grof", "where": "Bijlmerdreef", "at": 0}])})
        page.goto(base + "#give")
        settle(page)
        check(page.is_visible("a.pill[href='#bulky']") and "0 h left" not in page.inner_text("#view"),
              "own Geef door post older than 48 h offers the free pickup")
        check(page.evaluate("!!document.querySelector('link[rel=icon]')"), "favicon present")
        ctx.close()

        browser.close()

    print("\n".join(log))
    print("\n".join(failures) if failures else f"\nALL {len([l for l in log if l.startswith('PASS')])} CHECKS PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
