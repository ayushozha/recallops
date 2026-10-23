from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(__file__).parent
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    app = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
    errs = []; app.on("pageerror", lambda e: errs.append(str(e)))
    app.goto("http://127.0.0.1:8502", wait_until="networkidle")
    app.get_by_text("Interpret with Claude").wait_for(timeout=60000)
    app.locator("[data-testid='stSelectbox']").first.click(); app.keyboard.type("H-1339-2026"); app.wait_for_timeout(800)
    app.keyboard.press("Enter"); app.wait_for_timeout(3000)
    def shot(n, y=0):
        app.mouse.wheel(0, -6000); app.wait_for_timeout(300)
        if y: app.mouse.wheel(0, y); app.wait_for_timeout(1800)
        app.screenshot(path=str(OUT / f"s_{n}.png"))
    app.get_by_text("Interpret with Claude").click()
    app.get_by_text("Scope ready for human review").wait_for(timeout=150000); app.wait_for_timeout(1000)
    shot("1_notice", 200)
    app.get_by_role("button", name="Next: Where it went →").click(); app.wait_for_timeout(7000); shot("2_map", 330)
    app.get_by_role("button", name="Next: What we found →").click(); app.wait_for_timeout(4000); shot("3_found", 250)
    app.get_by_role("button", name="Next: Lock it down →").click(); app.wait_for_timeout(3000)
    app.get_by_role("button", name="Approve holds").click(); app.get_by_text("APPROVE_HOLDS:").wait_for(timeout=60000)
    app.locator("[data-testid='stHorizontalBlock']").filter(has_text="O-101").last.get_by_role("button", name="Try order").click(); app.wait_for_timeout(4000)
    app.locator("[data-testid='stHorizontalBlock']").filter(has_text="O-110").last.get_by_role("button", name="Try order").click(); app.wait_for_timeout(4000)
    shot("4_lock", 250)
    app.get_by_role("button", name="See the shipments stop on the map").click(); app.wait_for_timeout(7000); shot("5_map_after", 330)
    app.get_by_role("button", name="5 · Audit trail").click(); app.wait_for_timeout(4000); shot("6_audit", 250)
    print("errors:", errs[:3]); b.close()
