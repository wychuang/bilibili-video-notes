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


def check_flow(page, browser, base, site, chosen, route_request):
    page.goto(base + 'flow.html', wait_until='networkidle')
    data = page.evaluate('window.LEARNING_FLOW')
    paths = data['paths']
    assert {p['id'] for p in paths} == {'ai', 'product', 'research', 'learning', 'life', 'culture'}
    assert page.locator('.map-node').count() == len(paths)
    assert len(data['spine']) == 3
    assert page.locator('.spine-item').count() == page.locator('.gateway-card').count() == len(data['spine'])
    for index, item in enumerate(data['spine']):
        assert item['href'] and (site / 'courses/search-quality' / item['href']).is_file()
        assert page.locator('.spine-item').nth(index).get_attribute('href') == item['href']
        assert page.locator('.gateway-card').nth(index).get_attribute('href') == item['href']
        page.locator('.gateway-card').nth(index).click()
        assert page.locator('article').is_visible()
        page.go_back(wait_until='networkidle')
    for path in paths:
        page.locator(f'.map-node[data-path="{path["id"]}"]').click()
        assert page.locator('.branch').count() == len(path['branches']) > 0
        branch = path['branches'][0]
        page.locator(f'.branch[data-branch="{branch["id"]}"]').click()
        assert page.locator('.branch-content .card').count() == len(branch['lessons'])
        page.go_back()
        page.wait_for_function("!location.hash.slice(1).includes('/')")
        assert page.locator('.branch-content').count() == 0
        page.locator('[data-reset]').first.click()
    page.locator('#flow-search').fill('不存在的搜索测试xyz')
    assert page.locator('#search-results').get_by_text('没有找到相关内容', exact=False).is_visible()
    page.locator('#flow-search').fill(chosen)
    result = page.locator(f'.result[data-go-lesson="{chosen}"]').first
    assert result.is_visible()
    result.click()
    assert page.locator(f'#lesson-{chosen}').is_visible()
    assert page.locator(f'[data-done="{chosen}"]').is_checked()
    chosen_card = page.locator(f'#lesson-{chosen}')
    cover_link = chosen_card.locator('a.cover')
    assert cover_link.get_attribute('href') == chosen_card.locator('h4 a').get_attribute('href')
    assert cover_link.get_attribute('aria-label')
    cover_link.click()
    assert page.locator('article').is_visible()
    assert urlsplit(page.url).path.endswith(f'/lessons/{chosen}.html')
    page.go_back(wait_until='networkidle')
    page.locator(f'[data-done="{chosen}"]').uncheck()
    page.goto(base, wait_until='networkidle')
    assert not page.locator(f'[data-check="{chosen}"]').is_checked()
    page.locator(f'[data-check="{chosen}"]').check()
    page.goto(base + 'flow.html', wait_until='networkidle')
    page.locator('#motion-toggle').click()
    assert page.locator('#motion-toggle').get_attribute('aria-pressed') == 'true'
    assert page.evaluate("getComputedStyle(document.querySelector('.current')).animationPlayState") == 'paused'
    page.locator('#motion-toggle').click()
    assert page.locator('#motion-toggle').get_attribute('aria-pressed') == 'false'
    for width in (1440, 768, 390):
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(base + 'flow.html', wait_until='networkidle')
        page.locator('.map-node').first.click()
        page.locator('.branch').first.click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Flow overflow at {width}'
        page.screenshot(path=str(QA / f'flow-{width}.png'))
    cover_entry = next(((p, b, lesson) for p in paths for b in p['branches'] for lesson in b['lessons'] if lesson.get('cover')), None)
    assert cover_entry, 'Expected at least one local video cover'
    path, branch, lesson = cover_entry
    page.route('**/assets/covers/*.webp', lambda route: route.fulfill(status=200, content_type='image/webp', body=b'invalid image'))
    page.goto('about:blank')
    page.goto(base + f'flow.html#{path["id"]}/{branch["id"]}', wait_until='networkidle')
    card = page.locator(f'#lesson-{lesson["bvid"]}')
    card.scroll_into_view_if_needed()
    page.wait_for_function('(id) => !document.querySelector(`#lesson-${id} .cover img`)', arg=lesson['bvid'])
    assert card.locator('.cover-fallback').is_visible()
    page.unroute('**/assets/covers/*.webp')
    pending = [(p, b, lesson) for p in paths for b in p['branches'] for lesson in b['lessons'] if not lesson['ready']]
    assert pending, 'Expected at least one pending lesson'
    for path, branch, lesson in pending:
        page.goto(base + f'flow.html#{path["id"]}/{branch["id"]}', wait_until='networkidle')
        card = page.locator(f'#lesson-{lesson["bvid"]}')
        assert card.locator('a.cover').count() == 0
        assert card.locator('.cover').count() == 1
        assert card.get_by_role('link', name='观看原视频').get_attribute('href') == f'https://www.bilibili.com/video/{lesson["bvid"]}/'
    reduced = browser.new_context(reduced_motion='reduce')
    try:
        reduced.route('**/*', route_request)
        reduced_page = reduced.new_page()
        reduced_page.goto(base + 'flow.html', wait_until='networkidle')
        assert reduced_page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        assert reduced_page.evaluate("getComputedStyle(document.querySelector('.current')).animationName") == 'none'
    finally:
        reduced.close()
    local = browser.new_context()
    try:
        local.route('**/*', route_request)
        local_page = local.new_page()
        local_page.goto((site / 'courses/search-quality/flow.html').as_uri(), wait_until='load')
        assert local_page.locator('.map-node').count() == len(paths)
        local_page.locator('.map-node').first.click()
        assert local_page.locator('.branch').count() > 0
    finally:
        local.close()


def main():
    site = ROOT / ".state/course-site"
    if not (site / "index.html").is_file():
        raise SystemExit("Run build_course.py --stage first.")
    entries = json.loads((site / 'courses/search-quality/index.json').read_text(encoding='utf-8'))
    total = len(entries)
    readable = sum(bool(entry['ready']) for entry in entries)
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
                    if url.startswith((f"http://127.0.0.1:{server.server_port}/", 'file:')):
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
                assert page.locator(".lesson-card").count() == total
                assert page.locator("[data-check]").count() == readable
                home_cover = page.locator('.lesson-card a:has(> .card-cover)').first
                home_href = home_cover.get_attribute('href')
                assert home_cover.get_attribute('aria-label')
                home_cover.click()
                assert page.locator('article').is_visible()
                assert urlsplit(page.url).path.endswith('/' + home_href)
                page.go_back(wait_until='networkidle')
                for entry in (e for e in entries if not e['ready']):
                    pending_card = page.locator(f'.lesson-card[data-id="{entry["bvid"]}"]')
                    assert pending_card.locator('a:has(> .card-cover), a:has(> .cover-placeholder)').count() == 0
                page.screenshot(path=str(QA / "desktop.png"))
                page.locator("#course-search").fill("不存在的筛选测试")
                assert page.locator("#empty").is_visible()
                page.locator("#course-search").fill("RAG")
                assert 0 < page.locator(".lesson-card:visible").count() < total
                page.locator("#course-search").fill("")
                page.locator("#priority").select_option("核心")
                assert 0 < page.locator(".lesson-card:visible").count() < total
                page.locator("#priority").select_option("all")
                first = page.locator("[data-check]").first
                chosen = first.get_attribute("data-check")
                first.check()
                page.reload(wait_until="networkidle")
                assert page.locator(f'[data-check="{chosen}"]').is_checked()
                page.locator("#priority").select_option("unread")
                assert page.locator(".lesson-card:visible").count() == total - 1
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
                check_flow(page, browser, base, site, chosen, route_request)
                page.goto(base, wait_until='networkidle')
                page.locator('.start-links a').first.click()
                page.wait_for_load_state("networkidle")
                assert page.locator("article").is_visible()
                if page.locator("[data-done]").get_attribute("aria-pressed") != "true":
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
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.goto(base + 'lessons/BV1eaaL6EEZT.html', wait_until='networkidle')
                    page.locator('article table').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(QA / f'reader-table-{width}.png'))
                overflows = []
                for index, entry in enumerate(e for e in entries if e['ready']):
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 900})
                        page.goto(base + f"lessons/{entry['bvid']}.html", wait_until='networkidle')
                        page.evaluate('document.fonts.ready')
                        page.evaluate("document.querySelectorAll('figure img').forEach(img => img.loading = 'eager')")
                        page.wait_for_function("[...document.querySelectorAll('figure img')].every(img => img.complete && img.naturalWidth > 0)")
                        if not page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
                            overflows.append(f"{entry['bvid']} at {width}")
                        assert page.locator('article button.timecode').count() > 0
                        assert page.locator('.math-fallback').count() == 0, entry['bvid']
                        assert page.locator('#source-online-player').get_attribute('src') == 'about:blank'
                        assert page.locator('#load-online-video').is_visible()
                        assert page.locator('[data-done]').count() == 1
                    if (index + 1) % 10 == 0:
                        print(f'Checked {index + 1}/{readable} lessons at desktop and mobile widths', flush=True)
                assert not overflows, f"Lesson overflow: {', '.join(overflows)}"
                assert not errors, errors
                print(json.dumps({"status":"passed","cards":total,"readable":readable,"viewports":[1440,768,390],"checks":["filter","progress persistence","export/import","invalid import","flow navigation and search","flow history and shared progress","motion preferences","cover fallback","file access","lesson navigation","online playback routing fixture","18-part playlist","part timestamps","frame jump and zoom","MathML","all-lesson images and overflow","console/network"]}, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
