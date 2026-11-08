"""Smoke test for Onze Plek (index.html) at phone size.

Usage:  python3 tests/smoke_test.py [base_url]
Without base_url it serves the repo folder on a local port.
Writes screenshots to ./screenshots and exits non-zero on any failure.
"""
import functools, http.server, json, sys, threading
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
    const wrap = el.closest('[style*="overflow-x:auto"]');
    if (!wrap && (r.right > W + 0.5 || r.left < -0.5))
      out.offenders.push(el.tagName.toLowerCase() + (el.className ? '.' + el.className : '') + ' right=' + Math.round(r.right));
  }
  for (const card of document.querySelectorAll('.card')) {
    const q = card.getBoundingClientRect();
    for (const el of card.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width && r.right > q.right + 0.5 && !el.closest('[style*="overflow-x:auto"]'))
        out.offenders.push('outside its card: ' + el.tagName.toLowerCase() + (el.className ? '.' + el.className : ''));
    }
  }
  for (const el of document.querySelectorAll('[style*="overflow-x:auto"]'))
    if (el.scrollWidth > el.clientWidth + 1) out.scrollers.push(el.scrollWidth + '>' + el.clientWidth);
  return out;
}"""


def new_page(browser, lang, extra_storage=None):
    ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=2)
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
        browser = p.chromium.launch()

        # 1. Every tab, both languages: screenshots + overflow + console
        for lang in LANGS:
            for tab in TABS:
                extra = {"plek_spot": json.dumps("RET20507")} if tab == "spot" else None
                ctx, page, errs = new_page(browser, lang, extra)
                page.goto(base + "#" + tab)
                settle(page)
                cur = page.get_attribute("nav a[aria-current=page]", "href")
                check(cur == "#" + tab, f"{lang}/{tab}: tab is active ({cur})")
                check(page.evaluate("document.documentElement.lang") == lang, f"{lang}/{tab}: html lang={lang}")
                o = page.evaluate(OVERFLOW_JS)
                check(o["doc"] <= o["W"] and o["main"] <= o["mainClient"] and not o["offenders"],
                      f"{lang}/{tab}: no horizontal overflow (doc {o['doc']}/{o['W']}, main {o['main']}/{o['mainClient']}, offenders {o['offenders'][:3]})")
                if o["scrollers"]:
                    log.append(f"NOTE {lang}/{tab}: inner horizontal scroller(s) {o['scrollers']}")
                shoot(page, f"{lang}_{tab}")
                shoot(page, f"{lang}_{tab}_full", full=True)
                check(not errs, f"{lang}/{tab}: no console errors {errs}")
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

        # 3. Bulky flow up to the Geef door hint (both languages)
        for lang in LANGS:
            ctx, page, errs = new_page(browser, lang)
            page.goto(base + "#bulky")
            settle(page)
            page.click("[data-item='0']")
            page.click("[data-usable='1']")
            want = "keep it inside" if lang == "en" else "houd het binnen"
            check(want in page.inner_text("#view"), f"{lang}/bulky: Geef door hint says {want!r}")
            shoot(page, f"{lang}_bulky_flow_full", full=True)
            check(not errs, f"{lang}/bulky flow: no console errors {errs}")
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

        browser.close()

    print("\n".join(log))
    print("\n".join(failures) if failures else f"\nALL {len([l for l in log if l.startswith('PASS')])} CHECKS PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
