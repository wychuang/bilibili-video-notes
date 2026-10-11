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
from urllib.parse import parse_qs, urlsplit

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
                def route_request(route):
                    url = route.request.url
                    if url.startswith(f"http://127.0.0.1:{server.server_port}/"):
                        route.continue_()
                    elif urlsplit(url).hostname == 'player.bilibili.com':
                        # Test our routing contract without depending on third-party playback.
                        route.fulfill(status=200, content_type='text/html', body='<title>Playback routing fixture</title>')
                    else:
                        route.abort()
                ctx.route("**/*", route_request)
                page = ctx.new_page()
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
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
                assert page.locator('.part-button').count() == 18
                assert page.locator('figure img').count() == 4
                assert page.locator('#source-online-player').is_hidden()
                page.locator('#load-online-video').click()
                assert page.locator('#source-online-player').is_visible()
                stamp = page.locator('button.timecode[data-part="17"]').first
                seconds = stamp.get_attribute('data-seconds')
                stamp.click()
                query = parse_qs(urlsplit(page.locator('#source-online-player').get_attribute('src')).query)
                assert query['page'] == ['17'] and query['t'] == [seconds]
                assert query['bvid'] == ['BV1Vegf6nEag']
                fallback = parse_qs(urlsplit(page.locator('#online-fallback').get_attribute('href')).query)
                assert fallback['p'] == ['17'] and fallback['t'] == [seconds]
                page.locator('.part-button[data-part="18"]').click()
                assert page.locator('.part-button.active').get_attribute('data-part') == '18'
                assert parse_qs(urlsplit(page.locator('#source-online-player').get_attribute('src')).query)['page'] == ['18']
                page.locator('button.frame-image').first.click()
                assert page.locator('#frame-lightbox').is_visible()
                page.wait_for_function('document.querySelector("#lightbox-image").naturalWidth > 0')
                page.locator('.lightbox-close').click()
                assert not page.locator('#frame-lightbox').is_visible()
                frame_stamp = page.locator('.frame-jump').last
                frame_part = frame_stamp.get_attribute('data-part')
                frame_stamp.click()
                assert parse_qs(urlsplit(page.locator('#source-online-player').get_attribute('src')).query)['page'] == [frame_part]
                assert page.locator('#progress').text_content() == ''
                for width in (1440, 768, 390):
                    page.set_viewport_size({"width":width, "height":900})
                    page.goto(base, wait_until="networkidle")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Home overflow at {width}"
                    page.screenshot(path=str(QA / f"home-{width}.png"))
                    page.goto(base + "lessons/BV1Q3NUetEzV.html", wait_until="networkidle")
                    if width <= 900:
                        assert page.locator('.toc-toggle').get_attribute('aria-expanded') == 'false'
                        page.locator('.toc-toggle').click()
                        assert page.locator('.toc-toggle').get_attribute('aria-expanded') == 'true'
                        page.locator('.toc-toggle').click()
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
                entries = json.loads((site / 'courses/search-quality/index.json').read_text(encoding='utf-8'))
                for index, entry in enumerate(e for e in entries if e['ready']):
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 900})
                        page.goto(base + f"lessons/{entry['bvid']}.html", wait_until='networkidle')
                        page.evaluate('document.fonts.ready')
                        page.evaluate("document.querySelectorAll('figure img').forEach(img => img.loading = 'eager')")
                        page.wait_for_function("[...document.querySelectorAll('figure img')].every(img => img.complete && img.naturalWidth > 0)")
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f"Overflow: {entry['bvid']} at {width}"
                        assert page.locator('article button.timecode').count() > 0
                        assert page.locator('.math-fallback').count() == 0, entry['bvid']
                        assert page.locator('#source-online-player').get_attribute('src') == 'about:blank'
                        assert page.locator('#load-online-video').is_visible()
                        assert page.locator('[data-done]').count() == 1
                    if (index + 1) % 10 == 0:
                        print(f'Checked {index + 1}/51 lessons at desktop and mobile widths', flush=True)
                assert not errors, errors
                print(json.dumps({"status":"passed","cards":54,"readable":51,"viewports":[1440,768,390],"checks":["filter","progress persistence","export/import","invalid import","lesson navigation","online playback routing fixture","18-part playlist","part timestamps","frame jump and zoom","MathML","all-lesson images and overflow","console/network"]}, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
