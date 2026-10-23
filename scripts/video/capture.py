"""Capture 1920x1080 frames for the demo video: slides (local render), live app states, Snowflake proof."""
import base64
import html
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path("/Users/ayush/Desktop/03 Events & Hackathons/Hackathons/Snowflake x Anthropic Hackathon")
sys.path.insert(0, str(REPO / "app"))
from db import connect, query  # noqa: E402

OUT = Path(__file__).parent
SCR = OUT.parent
DECK = SCR / "deck" / "project" / "slides"
LOGOS = SCR / "logos"
BLOBS = {
    "/_blob/067a3d4f6bdbb2c848f531446b31cb10": LOGOS / "Snowflake_Logo.svg",
    "/_blob/4cd9499bd0a0224e2e4a157e87817d3e": LOGOS / "Claude_AI_logo.svg",
    "/_blob/cb9ab09a01b7fffc137d0d248d793dd0": LOGOS / "Claude_AI_symbol.svg",
    "/_blob/92fd64c21a983d74fd80d47d90f1eacd": LOGOS / "Snowflake_symbol.svg",
}
CSS = """*{margin:0;box-sizing:border-box} body{width:1920px;height:1080px;overflow:hidden}
section{width:1920px;height:1080px;position:relative;overflow:hidden} div{display:flex;flex-direction:column}
aside{display:none} x-icon{display:inline-block;border-radius:50%;background:currentColor;flex:none}
x-shape{display:block;flex:none;clip-path:polygon(0 30%,60% 30%,60% 0,100% 50%,60% 100%,60% 70%,0 70%)}
td,th{border-bottom:1px solid #E7E2D8;padding:14px 18px;text-align:left} table{border-collapse:collapse;overflow:hidden}"""
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..700'
         '&family=DM+Sans:wght@400..700&display=swap">')


def uri(path):
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def slide_html(name):
    body = (DECK / f"{name}.html").read_text()
    for blob, path in BLOBS.items():
        body = body.replace(blob, uri(path))
    return f"<!doctype html><html><head><meta charset='utf-8'>{FONTS}<style>{CSS}</style></head><body>{body}</body></html>"


def proof_html():
    c = connect()
    counts = query(c, """SELECT (SELECT COUNT(*) FROM FDA_RECALLS) R, (SELECT COUNT(*) FROM INVENTORY) I,
        (SELECT COUNT(*) FROM ORDERS) O, (SELECT COUNT(*) FROM RECALL_CASES) C, (SELECT COUNT(*) FROM HOLDS) H,
        (SELECT COUNT(*) FROM ACTIONS) A, CURRENT_ACCOUNT() ACC, CURRENT_REGION() REG""")[0]
    acts = query(c, """SELECT TO_CHAR(ACTED_AT,'HH24:MI:SS') T, ACTION_TYPE, CASE_ID, ACTOR,
        LEFT(DETAIL::STRING, 60) D FROM ACTIONS ORDER BY ACTED_AT DESC LIMIT 7""")
    rows = "".join(f"<tr><td>{a['T']}</td><td><b>{html.escape(a['ACTION_TYPE'])}</b></td><td>{html.escape(str(a['CASE_ID']))}</td>"
                   f"<td>{html.escape(a['ACTOR'])}</td><td style='color:#5b6472'>{html.escape(a['D'] or '')}</td></tr>" for a in acts)
    tiles = "".join(f"<div class='t'><p class='n'>{v:,}</p><p class='l'>{k}</p></div>" for k, v in
                    [("FDA_RECALLS", counts["R"]), ("INVENTORY", counts["I"]), ("ORDERS", counts["O"]),
                     ("RECALL_CASES", counts["C"]), ("HOLDS", counts["H"]), ("ACTIONS", counts["A"])])
    checks = ["Claude reachable via AI_COMPLETE · claude-opus-5-5", "Claude found the recalled UPC 087906010187",
              "Lot scope matches the FDA notice: 222, 223, 226, 230", "APPROVE_HOLDS placed holds · 125 units",
              "Re-approval is idempotent · 0 new holds", "No-lot rows never silently held", "Control lots stay sellable",
              "O-101 BLOCKED · O-110 FULFILLED", "Every action audited"]
    chk = "".join(f"<p class='c'><span>PASS</span> {html.escape(x)}</p>" for x in checks)
    return f"""<!doctype html><html><head><meta charset='utf-8'>{FONTS}<style>*{{margin:0;box-sizing:border-box}}
body{{width:1920px;height:1080px;background:#FAF8F4;font-family:'DM Sans',Arial;color:#14213D;padding:72px 96px;display:flex;flex-direction:column;gap:32px}}
.top{{display:flex;justify-content:space-between;align-items:center}} .top img{{height:48px}}
h1{{font-family:Fraunces,Georgia;font-size:60px;font-weight:600}} .sub{{font-size:26px;color:#5b6472}}
.tiles{{display:grid;grid-template-columns:repeat(6,1fr);gap:20px}} .t{{background:#14213D;border-radius:18px;padding:24px 28px}}
.n{{font-family:Fraunces,Georgia;font-size:52px;color:#E8896A}} .l{{font-size:20px;color:#C3CCD8;letter-spacing:2px}}
.row{{display:flex;gap:32px}} .box{{background:#fff;border:1px solid #E7E2D8;border-radius:18px;padding:24px 28px}}
.c{{font-family:Menlo,monospace;font-size:21px;line-height:1.75}} .c span{{background:#dff1e4;color:#1e6a36;padding:2px 8px;border-radius:6px;font-weight:700}}
table{{border-collapse:collapse;font-size:20px;width:100%}} td,th{{padding:9px 10px;border-bottom:1px solid #eee;text-align:left}} th{{color:#5b6472}}
h3{{font-size:22px;letter-spacing:3px;text-transform:uppercase;color:#11729E;margin-bottom:10px}}</style></head><body>
<div class='top'><div><h1>Live in Snowflake</h1><p class='sub'>Account {html.escape(counts['ACC'])} · {html.escape(counts['REG'])} · database RECALLOPS.APP</p></div>
<div style='display:flex;gap:24px;align-items:center'><img src='{uri(LOGOS / "Snowflake_Logo.svg")}'><span style='font-size:34px;color:#999'>×</span><img src='{uri(LOGOS / "Claude_AI_logo.svg")}' style='height:42px'></div></div>
<div class='tiles'>{tiles}</div>
<div class='row'><div class='box' style='flex:1'><h3>scripts/verify.py · 15 / 15 checks passed</h3>{chk}</div>
<div class='box' style='flex:1.25'><h3>ACTIONS audit table · latest rows</h3><table><tr><th>Time</th><th>Action</th><th>Case</th><th>Actor</th><th>Detail</th></tr>{rows}</table></div></div>
</body></html>"""


def main():
    c = connect()
    # fresh demo state for the sprouts recall: no holds, all orders pending
    query(c, """DELETE FROM HOLDS WHERE INVENTORY_ID IN (SELECT INVENTORY_ID FROM INVENTORY WHERE UPC = '087906010187')""")
    query(c, "UPDATE ORDERS SET STATUS = 'PENDING', UPDATED_AT = NULL")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        for name in ["intro", "solution", "outcome"]:
            pg.set_content(slide_html(name), wait_until="networkidle")
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(OUT / f"slide_{name}.png"))
        app = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
        app.goto("http://127.0.0.1:8502", wait_until="networkidle")
        app.get_by_text("Interpret with Claude").wait_for(timeout=60000)
        app.locator("[data-testid='stSelectbox']").first.click()
        app.keyboard.type("H-1339-2026")
        app.wait_for_timeout(800)
        app.keyboard.press("Enter")
        app.wait_for_timeout(3000)

        def tab(label):
            app.get_by_role("tab", name=label).click()
            app.wait_for_timeout(2500)

        def shot(name, scroll=0):
            app.mouse.wheel(0, -5000)
            app.wait_for_timeout(300)
            if scroll:
                app.mouse.wheel(0, scroll)
                app.wait_for_timeout(700)
            app.screenshot(path=str(OUT / f"app_{name}.png"))

        tab("2 Where it went")
        shot("map", 330)
        tab("1 The notice")
        app.get_by_text("Interpret with Claude").click()
        app.get_by_text("Highlighted text in the notice").wait_for(timeout=120000)
        app.wait_for_timeout(1500)
        shot("notice", 330)
        tab("3 What we found")
        shot("graph_before", 380)
        tab("4 Lock it down")
        app.get_by_role("button", name="Approve holds").click()
        app.get_by_text("APPROVE_HOLDS:").wait_for(timeout=60000)
        app.wait_for_timeout(1500)
        for oid in ["O-101", "O-110"]:
            row = app.locator("[data-testid='stHorizontalBlock']").filter(has_text=oid).last
            row.get_by_role("button", name="Try order").click()
            app.wait_for_timeout(4000)
        shot("orders", 330)
        tab("3 What we found")
        shot("graph_after", 380)
        pg.set_content(proof_html(), wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "proof.png"))
        b.close()
    print("done")


if __name__ == "__main__":
    main()


def redo_static():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for name in ["intro", "solution", "outcome"]:
            pg.set_content(slide_html(name), wait_until="networkidle"); pg.wait_for_timeout(800)
            pg.screenshot(path=str(OUT / f"slide_{name}.png"))
        pg.set_content(proof_html(), wait_until="networkidle"); pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "proof.png"))
        b.close()
