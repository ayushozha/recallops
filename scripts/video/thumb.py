import base64
from pathlib import Path
from playwright.sync_api import sync_playwright
D = Path(__file__).parent; L = D.parent / "logos"
def u(p, mime): return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
sf, cl = u(L / "Snowflake_Logo.svg", "image/svg+xml"), u(L / "Claude_AI_symbol.svg", "image/svg+xml")
graph = u(D / "app_graph_after.png", "image/png")
html = f"""<!doctype html><html><head><meta charset=utf-8>
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600..800&family=DM+Sans:wght@500;700;800&display=swap">
<style>*{{margin:0;box-sizing:border-box}}body{{width:1280px;height:720px;overflow:hidden;font-family:'DM Sans';
background:radial-gradient(circle at 80% 20%,#2B4170 0%,#14213D 55%,#0C1528 100%);color:#FAF8F4;position:relative}}
.shot{{position:absolute;right:-70px;top:250px;width:760px;height:320px;border-radius:18px;transform:rotate(-4deg);
box-shadow:0 30px 80px rgba(0,0,0,.55);border:6px solid #FAF8F4;overflow:hidden;background:#fff}}
.shot img{{width:100%;display:block;margin-top:-128px;width:900px;margin-left:-110px}}
.left{{position:absolute;left:64px;top:60px;width:640px}}
.tag{{display:inline-block;background:#E8553B;color:#fff;font-weight:800;font-size:28px;letter-spacing:2px;padding:10px 22px;border-radius:12px;transform:rotate(-2deg)}}
h1{{font-family:Fraunces;font-weight:800;font-size:132px;line-height:.95;margin-top:26px;letter-spacing:-2px}}
h2{{font-size:46px;font-weight:800;line-height:1.1;margin-top:22px}} h2 span{{color:#F0A58A}}
.logos{{position:absolute;left:64px;bottom:52px;display:flex;align-items:center;gap:18px;background:#FAF8F4;padding:14px 26px;border-radius:16px}}
.logos img{{height:40px}} .logos b{{color:#14213D;font-size:30px}} .x{{color:#8A8F98;font-size:28px}}
.stat{{position:absolute;right:56px;top:48px;background:#FAF8F4;color:#14213D;border-radius:18px;padding:16px 24px;text-align:right;transform:rotate(3deg);box-shadow:0 14px 40px rgba(0,0,0,.4)}}
.stat p:first-child{{font-family:Fraunces;font-weight:800;font-size:64px;line-height:1;color:#C2412A}} .stat p:last-child{{font-size:22px;font-weight:700}}
</style></head><body>
<div class=shot><img src="{graph}"></div>
<div class=stat><p>175+</p><p>stores still sold<br>recalled formula</p></div>
<div class=left><span class=tag>RECALL ALERT</span><h1>RecallOps</h1><h2>Stop recalled stock<br><span>before it ships.</span></h2></div>
<div class=logos><img src="{sf}"><span class=x>×</span><img src="{cl}" style="height:40px"><b>Claude</b></div>
</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome"); pg = b.new_page(viewport={"width": 1280, "height": 720})
    pg.set_content(html, wait_until="networkidle"); pg.wait_for_timeout(800)
    pg.screenshot(path=str(D / "RecallOps-thumbnail.png")); b.close()
print("ok")
