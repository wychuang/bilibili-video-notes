"""Optional real-browser smoke test using an existing Playwright and Edge.

No installation, personal profile, or external website is used. Artifacts and
browser temp files stay under this non-system-drive project's ignored .state.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
if os.name == "nt" and ROOT.drive.casefold() == os.environ.get("SystemDrive", "C:").casefold():
    raise SystemExit("Browser QA requires a non-system-drive project.")
QA = ROOT / ".state/course-qa"
QA.mkdir(parents=True, exist_ok=True)
for folder in ("temp", "downloads", "traces", "cache"):
    (QA / folder).mkdir(exist_ok=True)
for key in ("TEMP", "TMP", "TMPDIR"):
    os.environ[key] = str(QA / "temp")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    site = ROOT / ".state/course-site"
    if not (site / "index.html").is_file():
        raise SystemExit("Run build_course.py --stage first.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(site)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/courses/search-quality/"
    errors = []
    try:
        with sync_playwright() as pw:
            executable = os.environ.get("COURSE_BROWSER")
            if not executable and os.name == "nt":
                executable = str(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe")
            browser = pw.chromium.launch(executable_path=executable, headless=True,
                downloads_path=str(QA / "downloads"), traces_dir=str(QA / "traces"),
                args=[f"--disk-cache-dir={QA / 'cache'}", "--disable-background-networking", "--disable-component-update", "--no-first-run"])
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(f"http://127.0.0.1:{server.server_port}/") else route.abort())
                page = ctx.new_page()
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)
                page.goto(base, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                assert page.locator(".lesson-card").count() == 54
                assert page.locator("[data-check]").count() == 51
                page.screenshot(path=str(QA / "desktop.png"))
                page.locator("#course-search").fill("不存在的筛选测试")
                assert page.locator("#empty").is_visible()
                page.locator("#course-search").fill("RAG")
                assert 0 < page.locator(".lesson-card:visible").count() < 54
                page.locator("#course-search").fill("")
                page.locator("#priority").select_option("核心")
                assert 0 < page.locator(".lesson-card:visible").count() < 54
                page.locator("#priority").select_option("all")
                first = page.locator("[data-check]").first
                chosen = first.get_attribute("data-check")
                first.check()
                page.reload(wait_until="networkidle")
                assert page.locator(f'[data-check="{chosen}"]').is_checked()
                page.locator("#priority").select_option("unread")
                assert page.locator(".lesson-card:visible").count() == 53
                page.locator("#priority").select_option("all")
                with page.expect_download() as info:
                    page.locator("#export-progress").click()
                exported = QA / "downloads/progress.json"
                info.value.save_as(str(exported))
                value = json.loads(exported.read_text(encoding="utf-8"))
                assert value["course"] == "search-quality" and chosen in value["done"]
                page.evaluate("localStorage.clear()")
                page.reload(wait_until="networkidle")
                page.locator("#import-progress").set_input_files(str(exported))
                page.wait_for_function("document.querySelector('#transfer-message').textContent.includes('已合并')")
                assert page.locator(f'[data-check="{chosen}"]').is_checked()
                page.locator("#import-progress").set_input_files({"name":"bad.json", "mimeType":"application/json", "buffer":b'{"done": ["bad"]}'})
                page.wait_for_function("document.querySelector('#transfer-message').textContent.includes('无法导入')")
                page.locator('.start-links a').first.click()
                page.wait_for_load_state("networkidle")
                assert page.locator("article").is_visible()
                page.locator("[data-done]").click()
                assert page.locator("[data-done]").get_attribute("aria-pressed") == "true"
                page.reload(wait_until="networkidle")
                assert page.locator("[data-done]").get_attribute("aria-pressed") == "true"
                page.goto(base + "lessons/BV1Vegf6nEag.html", wait_until="networkidle")
                assert page.locator('a.timecode[href*="p=17"]').count() > 0
                assert page.locator('figure img').count() == 2
                with page.expect_popup() as info:
                    page.locator('figure a').first.click()
                popup = info.value; popup.wait_for_load_state()
                assert ".jpg" in popup.url
                popup.close()
                for width in (1440, 768, 390):
                    page.set_viewport_size({"width":width, "height":900})
                    page.goto(base, wait_until="networkidle")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Home overflow at {width}"
                    page.screenshot(path=str(QA / f"home-{width}.png"))
                    page.goto(base + "lessons/BV1Q3NUetEzV.html", wait_until="networkidle")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Lesson overflow at {width}"
                    page.locator('figure').first.scroll_into_view_if_needed()
                    page.wait_for_function("[...document.querySelectorAll('figure img')].filter(x=>x.getBoundingClientRect().top < innerHeight).every(x=>x.complete && x.naturalWidth>0)")
                    page.screenshot(path=str(QA / f"lesson-{width}.png"))
                    page.goto(base + "lessons/BV1Wzjg65EM6.html", wait_until="networkidle")
                    assert page.locator('math').count() > 0
                    assert page.locator('.math-fallback').count() == 0
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Formula overflow at {width}"
                    page.locator('.math-display').scroll_into_view_if_needed()
                    page.screenshot(path=str(QA / f"formula-{width}.png"))
                assert not errors, errors
                print(json.dumps({"status":"passed","cards":54,"readable":51,"viewports":[1440,768,390],"checks":["filter","progress persistence","export/import","invalid import","lesson navigation","part timestamps","frame zoom","MathML","overflow","console/network"]}, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
