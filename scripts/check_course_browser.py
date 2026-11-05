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
    page.wait_for_function('window.atlas && document.querySelectorAll("[data-node]").length > 0')
    counts = page.evaluate("""() => {
      const g = window.atlas.graph;
      return {lessons: g.nodes.filter(n => n.type === 'lesson').length,
              branches: g.nodes.filter(n => n.type === 'branch').length,
              spine: g.nodes.filter(n => n.type === 'spine').length,
              paths: g.routes.map(p => p.id)};
    }""")
    entries = json.loads((site / 'courses/search-quality/index.json').read_text(encoding='utf-8'))
    extras = page.evaluate('(window.LEARNING_FLOW.external || []).length')
    assert counts['lessons'] == len(entries) + extras
    assert set(counts['paths']) == {'ai', 'product', 'research', 'learning', 'life', 'culture'}
    assert counts['spine'] == len(page.evaluate('window.LEARNING_FLOW.spine')) == 3
    assert page.locator('#world-labels [data-node]').count() == counts['lessons'] + counts['branches'] + counts['spine'] + len(counts['paths'])
    assert page.locator('#route-nav [data-route]').count() == len(counts['paths'])
    assert page.locator('#atlas-stage').get_attribute('data-renderer') == '3d'
    page.locator('[data-action=fullscreen]').click()
    page.wait_for_function('document.fullscreenElement !== null')
    page.locator('[data-action=fullscreen]').click()
    page.wait_for_function('document.fullscreenElement === null')
    page.locator('[data-action=list]:visible').first.click()
    assert page.locator('#library-panel .library-item').count() == counts['lessons']
    page.locator('[data-action=close-list]').click()
    for path in counts['paths']:
        page.locator(f'#route-nav [data-route="{path}"]').click()
        assert page.evaluate('window.atlas.selected') == path
        assert page.locator('#inspector').is_visible()
        assert page.locator('#inspector .detail-list button').count() > 0
    page.locator('#route-nav [data-route="ai"]').click()
    page.locator('#inspector .detail-list button').first.click()
    assert page.evaluate('window.atlas.selected').startswith('ai/')
    page.go_back()
    page.wait_for_function('window.atlas.selected === "ai"')
    page.wait_for_function('Object.keys(window.atlas.scene.state).every(k => Math.abs(window.atlas.scene.state[k] - window.atlas.scene.target[k]) < 0.01)')
    page.screenshot(path=str(QA / 'atlas-route-1440.png'))
    page.locator('[data-action=overview]').click()
    page.locator('#atlas-stage').hover(position={'x': page.viewport_size['width'] // 2, 'y': page.viewport_size['height'] // 2})
    page.mouse.wheel(0, 120)
    page.wait_for_function('window.atlas.step === 1')
    assert page.evaluate('window.atlas.selected.startsWith("spine/")')
    stage = page.locator('#atlas-stage').bounding_box()
    x, y = stage['x'] + stage['width'] * .52, stage['y'] + stage['height'] * .38
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 80, y + 40, steps=6)
    page.mouse.up()
    assert page.evaluate('window.atlas.free')
    before = page.evaluate('window.atlas.scene.target.zoom')
    page.locator('[data-action=zoom-in]').click()
    assert page.evaluate('window.atlas.scene.target.zoom') > before
    page.locator('#atlas-search').fill('不存在的搜索测试xyz')
    assert page.locator('#search-results .result-empty').is_visible()
    page.locator('#atlas-search').fill(chosen)
    result = page.locator(f'#search-results [data-select$="/{chosen}"]').first
    assert result.is_visible()
    result.click()
    assert page.evaluate('window.atlas.selected').endswith('/' + chosen)
    assert page.locator(f'#inspector [data-done="{chosen}"]').is_checked()
    page.wait_for_function('Object.keys(window.atlas.scene.state).every(k => Math.abs(window.atlas.scene.state[k] - window.atlas.scene.target[k]) < 0.01)')
    page.screenshot(path=str(QA / 'atlas-lesson-1440.png'))
    link = page.locator('#inspector .primary-link')
    assert link.get_attribute('href') == f'lessons/{chosen}.html'
    link.click()
    assert page.locator('article').is_visible()
    assert urlsplit(page.url).path.endswith(f'/lessons/{chosen}.html')
    page.go_back(wait_until='networkidle')
    assert page.locator(f'#inspector [data-done="{chosen}"]').is_checked()
    page.locator(f'#inspector [data-done="{chosen}"]').uncheck()
    page.goto(base, wait_until='networkidle')
    assert not page.locator(f'[data-check="{chosen}"]').is_checked()
    page.locator(f'[data-check="{chosen}"]').check()
    page.goto(base + 'flow.html', wait_until='networkidle')
    pending = page.evaluate("""() => window.atlas.graph.nodes.filter(n =>
      n.type === 'lesson' && !n.lesson.ready && !n.lesson.external).map(n => ({id:n.id,bvid:n.lesson.bvid}))""")
    assert len(pending) == sum(not e['ready'] for e in entries)
    for item in pending:
        page.evaluate('(id) => window.atlas.selectNode(id)', item['id'])
        link = page.locator('#inspector .primary-link')
        assert link.get_attribute('href') == f'https://www.bilibili.com/video/{item["bvid"]}/'
        assert link.get_attribute('rel') == 'noopener noreferrer'
    external = page.evaluate("""() => window.atlas.graph.nodes.filter(n =>
      n.type === 'lesson' && n.lesson.external).map(n => ({id:n.id,href:n.lesson.href}))""")
    assert len(external) == extras
    for item in external:
        page.evaluate('(id) => window.atlas.selectNode(id)', item['id'])
        assert page.locator('#inspector .primary-link').get_attribute('href') == item['href']
    page.locator('[data-action=motion]').click()
    assert page.locator('[data-action=motion]').get_attribute('aria-pressed') == 'true'
    assert page.evaluate('window.atlas.scene.paused')
    paused_time = page.evaluate('window.atlas.scene.time')
    page.wait_for_timeout(200)
    assert page.evaluate('window.atlas.scene.time') == paused_time
    page.locator('[data-action=motion]').click()
    assert not page.evaluate('window.atlas.scene.paused')
    for width, height in ((1920, 1080), (1440, 900), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.goto(base + 'flow.html', wait_until='networkidle')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('[data-action=list]:visible').count() >= 1
        if width == 1920:
            page.wait_for_function('document.querySelectorAll(".world-node.featured").length >= 3')
        if width == 390:
            assert page.evaluate("""() => {
              const boxes = [...document.querySelectorAll('.world-node.spine .node-title, .world-node.path .node-title')].map(e => e.getBoundingClientRect());
              return boxes.every((a, i) => boxes.slice(i + 1).every(b => a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top));
            }""")
        page.screenshot(path=str(QA / f'atlas-{width}.png'))
    page.route('**/assets/covers/*.webp', lambda route: route.fulfill(status=200, content_type='image/webp', body=b'invalid image'))
    page.goto('about:blank')
    page.goto(base + 'flow.html', wait_until='networkidle')
    covered = page.evaluate("window.atlas.graph.nodes.find(n => n.type === 'lesson' && n.lesson.cover).id")
    page.evaluate('(id) => window.atlas.selectNode(id)', covered)
    page.wait_for_function('document.querySelector("#inspector .detail-cover")?.hidden === true')
    page.unroute('**/assets/covers/*.webp')
    reduced = browser.new_context(reduced_motion='reduce')
    try:
        reduced.route('**/*', route_request)
        reduced_page = reduced.new_page()
        reduced_page.goto(base + 'flow.html', wait_until='networkidle')
        assert reduced_page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches && window.atlas.scene.reduced")
    finally:
        reduced.close()
    fallback = browser.new_context()
    try:
        fallback.route('**/*', route_request)
        fallback.add_init_script("""(() => {
          const original = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = function(type, ...args) {
            if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') return null;
            return original.call(this, type, ...args);
          };
        })()""")
        fallback_page = fallback.new_page()
        fallback_page.goto(base + 'flow.html', wait_until='networkidle')
        assert fallback_page.locator('#atlas-stage').get_attribute('data-renderer') == '2d'
        fallback_page.locator('[data-action=list]:visible').first.click()
        assert fallback_page.locator('#library-panel .library-item').count() == counts['lessons']
    finally:
        fallback.close()
    local = browser.new_context()
    try:
        local.route('**/*', route_request)
        local_page = local.new_page()
        local_page.goto((site / 'courses/search-quality/flow.html').as_uri(), wait_until='load')
        assert local_page.locator('#world-labels [data-node]').count() == page.locator('#world-labels [data-node]').count()
        local_page.locator('[data-action=list]:visible').first.click()
        assert local_page.locator('#library-panel .library-item').count() == counts['lessons']
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
                external_home = page.locator('.external-card')
                external_entries = json.loads((site / 'courses/search-quality/external.json').read_text(encoding='utf-8'))
                assert external_home.count() == len(external_entries) == 7
                assert page.locator('a[href="https://hackertube.org/categories"]').count() > 0
                assert all(external_home.nth(i).locator('h3 a').get_attribute('href') == entry['url'] for i, entry in enumerate(external_entries))
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
                print(json.dumps({"status":"passed","cards":total,"readable":readable,"viewports":[1920,1440,768,390],"checks":["filter","progress persistence","export/import","invalid import","3D navigation, search, wheel, drag and zoom","history and shared progress","external links","fullscreen","motion preferences","cover fallback","2D fallback","file access","lesson navigation","online playback routing fixture","18-part playlist","part timestamps","frame jump and zoom","MathML","all-lesson images and overflow","console/network"]}, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
