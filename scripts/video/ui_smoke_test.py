from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(__file__).parent
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    app = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
    errs = []
    app.on("pageerror", lambda e: errs.append(str(e)))
    app.goto("http://127.0.0.1:8502", wait_until="networkidle")
    app.get_by_text("Interpret with Claude").wait_for(timeout=60000)
    app.locator("[data-testid='stSelectbox']").first.click(); app.keyboard.type("H-1339-2026"); app.wait_for_timeout(800)
    app.keyboard.press("Enter"); app.wait_for_timeout(3000)
    def tab(label): app.get_by_role("tab", name=label).click(); app.wait_for_timeout(3000)
    def shot(name, scroll=0):
        app.mouse.wheel(0, -5000); app.wait_for_timeout(300)
        if scroll: app.mouse.wheel(0, scroll); app.wait_for_timeout(1500)
        app.screenshot(path=str(OUT / f"t_{name}.png"))
    app.get_by_text("Interpret with Claude").click()
    app.get_by_text("Scope ready for human review").wait_for(timeout=150000)
    app.wait_for_timeout(1500); shot("findings", 250)
    tab("2 Where it went"); shot("map", 250)
    tab("3 What we found"); app.get_by_role("button", name="▶ Trace the recall").click()
    app.wait_for_timeout(1300); shot("trace_mid", 330); app.wait_for_timeout(3500); shot("trace_end", 330)
    tab("4 Lock it down"); app.get_by_role("button", name="Approve holds").click()
    app.get_by_text("APPROVE_HOLDS:").wait_for(timeout=60000); app.wait_for_timeout(2500)
    row = app.locator("[data-testid='stHorizontalBlock']").filter(has_text="O-101").last
    row.get_by_role("button", name="Try order").click(); app.wait_for_timeout(5000)
    shot("banner", 0); shot("orders_graph", 700)
    tab("2 Where it went"); shot("map_after", 520)
    print("page errors:", errs[:3])
    b.close()
