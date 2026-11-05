"""Build the full learning reader and a whitelist-only Pages artifact."""
from __future__ import annotations

import argparse
from datetime import date
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "courses/search-quality"
STATE = ROOT / ".state/course-evidence"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_learning_flow


def relative(path, base):
    return quote(Path(os.path.relpath(path, base)).as_posix(), safe="/.-_")


def reviewed_frames(text, bvid):
    """Resolve only the exact source frames named by the article."""
    registry_path = COURSE / "assets/frames.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    frames = []
    seen = set()
    for part, timestamp in re.findall(r"\[\[FRAME:(?:P(\d+)\|)?(\d{2}:\d{2}:\d{2})\|", text):
        record = next((r for r in registry if r["bvid"] == bvid and r["part"] == int(part or 1) and r["timecode"] == timestamp and r.get("inspected")), None)
        if not record:
            raise ValueError(f"Unreviewed frame marker in {bvid}: {timestamp}")
        path = (COURSE / "assets" / record["file"]).resolve()
        if not path.is_relative_to((COURSE / "assets").resolve()) or not path.is_file() or path.suffix.lower() not in {".jpg", ".png", ".webp"}:
            raise ValueError("Missing or unsafe reviewed frame")
        identity = (int(part or 1), timestamp)
        if identity in seen:
            raise ValueError(f"Repeated frame marker in {bvid}: {timestamp}")
        seen.add(identity)
        h, m, s = map(int, timestamp.split(":"))
        frames.append(dict(index=len(frames) + 1, path=path, timecode=timestamp,
                           timestamp_seconds=h * 3600 + m * 60 + s,
                           part_index=int(part) if part else 0))
    return frames


def render(text, source, target, bvid):
    from bili_notes.summary import _markdown_to_safe_html
    frames = reviewed_frames(text, bvid)
    for frame in frames:
        frame["relative_path"] = relative(frame["path"], target.parent)
    return _markdown_to_safe_html(text, frames)


def source_metadata(bvid, previous):
    """Public identity/playlist only; never propagate private source fields."""
    candidate = STATE / bvid / "source.json"
    if not candidate.is_file():
        jobs = list((ROOT / "library").glob(f"*/*__{bvid}*"))
        candidate = next((p / "collection.json" for p in jobs if (p / "collection.json").is_file()), None)
        if candidate is None:
            candidate = next((p / "source.json" for p in jobs if (p / "source.json").is_file()), None)
    raw = json.loads(candidate.read_text(encoding="utf-8")) if candidate and candidate.is_file() else previous
    source_pages = raw.get("pages") or (raw.get("parts") if isinstance(raw.get("parts"), list) else [])
    pages = []
    for p in source_pages:
        number = p.get("page") or p.get("index") or p.get("part")
        title = p.get("display_title") or p.get("title") or p.get("part")
        pages.append(dict(part=int(number), title=str(title), duration_seconds=p.get("duration_seconds", p.get("duration", 0))))
    duration = raw.get("total_duration_seconds", raw.get("duration_seconds"))
    if not pages:
        pages = [dict(part=1, title=str(raw.get("title") or bvid), duration_seconds=duration or 0)]
    return dict(bvid=bvid, title=raw.get("title") or bvid, uploader=raw.get("uploader", ""),
                duration_seconds=duration, pages=pages, url=f"https://www.bilibili.com/video/{bvid}/")


def reading_strength(item, text):
    strength = item.get("strength")
    if strength is None:
        block = "\n".join(line for line in text.splitlines() if line.startswith(">"))
        if re.search(r"(?:快速阅读|阅读强度[：:]\s*快速)", block):
            strength = "quick"
        elif re.search(r"(?:标准阅读|阅读强度[：:]\s*标准)", block):
            strength = "standard"
        else:
            strength = "deep"
    if strength not in {"quick", "standard", "deep"}:
        raise ValueError(f"Invalid reading strength: {item['bvid']}")
    return strength


def render_lesson(source, target, item, metadata, title, module_label):
    from bili_notes.summary import render_summary_html
    text = source.read_text(encoding="utf-8")
    validate_article(text, metadata)
    frames = reviewed_frames(text, item["bvid"])
    videos = [dict(part=p["part"], title=p["title"], duration=f"{int(p['duration_seconds'] or 0) // 60:02d}:{int(p['duration_seconds'] or 0) % 60:02d}", path=None) for p in metadata["pages"]]
    for video in videos:
        poster = next((f["path"] for f in frames if int(f.get("part_index") or 1) == video["part"]), None)
        if poster:
            video["poster"] = poster
    strength = reading_strength(item, text)
    render_summary_html(COURSE, strength, source, {**metadata, "title": title}, {},
                        page_videos=videos, visual_frames_override=frames,
                        related_paths={"课程目录": COURSE / "index.html"}, output_path=target)
    page = target.read_text(encoding="utf-8")
    controls = (f'<div class="course-controls"><a href="../index.html#{html.escape(item["module"], quote=True)}">'
                f'← {html.escape(module_label)}</a><a href="../flow.html">学习脉络 ↗</a><button class="done" data-done="{item["bvid"]}" '
                'type="button" aria-pressed="false">标记学过</button></div>')
    style = '<style>.course-controls{display:grid;gap:12px;margin-top:18px;padding-top:16px;border-top:1px solid var(--line)}.course-controls .done{padding:9px 12px;border:1px solid #9bc8b4;border-radius:7px;background:#edf8f2;color:#126c4e;font:600 14px/1.5 system-ui,sans-serif;cursor:pointer}.course-controls .done[aria-pressed="true"]{color:white;background:#126c4e}.course-controls .done:focus-visible{outline:3px solid #b59168;outline-offset:3px}</style>'
    page = page.replace('</head>', style + '<script src="../assets/reader.js" defer></script></head>', 1)
    page = page.replace('</aside>', controls + '</aside>', 1)
    page = page.replace('<article>', f'<article data-lesson="{item["bvid"]}">', 1)
    target.write_text(page, encoding="utf-8", newline="\n")


def validate_article(text, metadata):
    if re.search(r"!\[[^\]]*\]\(", text):
        raise ValueError("Use reviewed FRAME markers, not raw Markdown images")
    if re.search(r"^#{1,6}\s+.*(?:证据说明|制作说明|整理方法|核对记录)", text, re.M):
        raise ValueError("Production notes do not belong in a learning article")
    durations = {p["part"]: float(p["duration_seconds"] or 0) for p in metadata["pages"]}
    timecodes = re.findall(r"\[(?:P(\d+) )?(\d{2}):(\d{2}):(\d{2})\]", text)
    timecodes += re.findall(r"\[\[FRAME:(?:P(\d+)\|)?(\d{2}):(\d{2}):(\d{2})\|", text)
    for part, h, m, s in timecodes:
        number = int(part or 1)
        if number not in durations or (len(durations) > 1 and not part):
            raise ValueError(f"Missing or invalid timestamp part: {metadata['bvid']}")
        seconds = int(h) * 3600 + int(m) * 60 + int(s)
        if int(m) >= 60 or int(s) >= 60 or (durations[number] and seconds > durations[number]):
            raise ValueError(f"Timestamp exceeds part duration: {metadata['bvid']} P{number} {h}:{m}:{s}")


def shell(title, content, *, lesson=False):
    asset = "../assets" if lesson else "assets"
    home = "../index.html" if lesson else "index.html"
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="description" content="围绕具体问题展开的中文学习笔记，配合实例、关键画面和时间导航。">
<title>{html.escape(title)}</title><link rel="stylesheet" href="{asset}/reader.css"><script src="{asset}/reader.js" defer></script><style>.card-cover{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px;margin-bottom:12px}}.cover-placeholder{{display:grid;place-items:center;aspect-ratio:16/9;background:#e9eee9;color:#536b5e;border-radius:6px;margin-bottom:12px;font-size:13px}}.external-resources{{margin:42px 0;padding:26px;border:1px solid #cbd8cc;border-radius:12px;background:#f4f8f4}}.external-heading{{display:flex;justify-content:space-between;align-items:end;gap:24px;margin-bottom:20px}}.external-heading h2{{margin:.3em 0}}.external-heading p{{max-width:720px;color:#52665a}}.external-heading>a,.external-discovery{{color:#327658;font-weight:650}}.external-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;list-style:none;padding:0;margin:0}}.external-card{{padding:18px;border:1px solid #d8e2d9;border-radius:9px;background:#fff}}.external-cover{{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px;margin:12px 0}}.external-card h3{{font-size:17px;line-height:1.45}}.external-card p{{line-height:1.65;color:#405147}}.external-card .external-prereq{{font-size:13px;color:#68766d}}.external-card .card-eyebrow{{display:flex;justify-content:space-between;gap:12px;color:#4b725b;font-size:12px}}@media(max-width:640px){{.external-heading{{display:block}}.external-heading>a{{display:inline-block;margin:10px 0}}}}</style></head>
<body><a class="skip" href="#main">跳到正文</a><header class="topbar"><a class="brand" href="{home}">学习笔记</a><a href="{'../flow.html' if lesson else 'flow.html'}">学习脉络 ↗</a></header>
{content}<footer>视频与截图版权归原作者 · 正文和公式离线可读，视频回看需要联网。<br>学习进度保存在当前浏览器，可手动导出到其他设备。</footer></body></html>'''


def external_section(external):
    cards = []
    for item in external:
        cover = f'<img class="external-cover" src="{html.escape(item["cover"], quote=True)}" alt="" loading="lazy">' if item.get("cover") else ""
        cards.append(f'''<li class="external-card"><div class="card-eyebrow"><span>外部观看</span><span>{html.escape(item['author'])}</span></div>{cover}<h3><a href="{html.escape(item['url'], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(item['title'])} ↗</a></h3><p>{html.escape(item['summary'])}</p><p class="external-prereq"><strong>建议前置：</strong>{html.escape(item['prerequisites'])}</p><a class="external-discovery" href="{html.escape(item['hacker_tube_url'], quote=True)}" target="_blank" rel="noopener noreferrer">HackerTube 条目 ↗</a></li>''')
    cards = ''.join(cards)
    return f'''<section class="external-resources" id="external-resources"><div class="external-heading"><div><div class="eyebrow">外部观看入口 / FOUNDATION VIDEOS</div><h2>精选主干视频</h2><p>以下资源由原作者或课程机构发布，点击后会打开外部视频；它们尚未整理成本地课程笔记。</p></div><a href="https://hackertube.org/categories" target="_blank" rel="noopener noreferrer">浏览 HackerTube 分类 ↗</a></div><ul class="external-grid">{cards}</ul></section>'''


def build():
    catalog = json.loads((COURSE / "catalog.json").read_text(encoding="utf-8"))
    external = build_learning_flow.load_external(COURSE)
    previous_path = COURSE / "index.json"
    previous = {e["bvid"]: e for e in json.loads(previous_path.read_text(encoding="utf-8"))} if previous_path.exists() else {}
    lessons = COURSE / "lessons"
    lessons.mkdir(exist_ok=True)
    missing = [bv for bv, old in previous.items() if old.get("ready") and not (lessons / f"{bv}.md").is_file()]
    if missing:
        raise ValueError("Complete the course Markdown revisions before building: " + ", ".join(missing))
    entries = []
    for item in catalog["videos"]:
        bvid = item["bvid"]
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
            raise ValueError("Invalid catalog video identity")
        metadata = source_metadata(bvid, {**item, **previous.get(bvid, {})})
        source = lessons / f"{bvid}.md"
        exists = bool(source and source.exists())
        text = source.read_text(encoding="utf-8") if exists else ""
        title_match = re.search(r"^# (.+)", text)
        title = title_match[1] if title_match else metadata.get("title", bvid)
        record = {k: item[k] for k in ("bvid", "module", "priority", "reason")}
        record.update({k: item[k] for k in ("strength", "flow_role", "start") if k in item})
        record.update(title=title, ready=exists, reused=bool(item.get("reuse")), uploader=metadata.get("uploader", ""), duration_seconds=metadata.get("duration_seconds"), parts=len(metadata["pages"]), pages=metadata["pages"])
        entries.append(record)
        if not exists:
            continue
        target = lessons / f"{bvid}.html"
        render_lesson(source, target, item, metadata, title, catalog["modules"][item["module"]])
    ready = sum(e["ready"] for e in entries)
    groups = []
    for module, label in catalog["modules"].items():
        cards = []
        for e in [r for r in entries if r["module"] == module]:
            status = "可阅读" if e["ready"] else "暂未提供讲解"
            href = f"lessons/{e['bvid']}.html" if e["ready"] else f"https://www.bilibili.com/video/{e['bvid']}/"
            action = "开始阅读" if e["ready"] else "查看原视频"
            cover = COURSE / "assets/covers" / f"{e['bvid']}.webp"
            image = f'<img class="card-cover" src="assets/covers/{e["bvid"]}.webp" alt="" loading="lazy">' if cover.is_file() else '<div class="cover-placeholder">暂无视频封面</div>'
            if e["ready"]:
                image = f'<a href="{href}" aria-label="打开笔记：{html.escape(e["title"], quote=True)}">{image}</a>'
            cards.append(f'''<li class="lesson-card" data-priority="{html.escape(e['priority'], quote=True)}" data-search="{html.escape(e['title']+' '+e['reason'], quote=True)}" data-id="{e['bvid']}">{image}<div class="card-eyebrow"><span>{html.escape(e['priority'])}</span><span>{status}</span></div><h3><a href="{href}">{html.escape(e['title'])}</a></h3><p>{html.escape(e['reason'])}</p><div class="card-bottom"><a href="{href}">{action} ↗</a>{f'<label><input type="checkbox" data-check="{e["bvid"]}"> 学过</label>' if e['ready'] else ''}</div></li>''')
        groups.append(f'<section id="{module}" class="module"><h2>{html.escape(label)}</h2><ul class="lesson-grid">{"".join(cards)}</ul></section>')
    module_links = ''.join(f'<a href="#{m}">{html.escape(n)}</a>' for m, n in catalog['modules'].items())
    starter = [("BV1ojfDBSEPv", "概念地图"), ("BV1YvMy6iE1r", "先定义怎样才算好"), ("BV1Pmux6zEqQ", "把好坏写成标准"), ("BV1MRMnz1EGW", "把标准变成数据"), ("BV1s43z67Ezv", "让信息被理解"), ("BV12suS6rEA8", "用练习检验掌握")]
    starters = ''.join(f'<a href="lessons/{bv}.html"><span>0{i}</span>{label} →</a>' for i, (bv, label) in enumerate(starter, 1) if any(e['bvid'] == bv and e['ready'] for e in entries))
    content = f'''<main id="main" class="home"><section class="hero"><div class="eyebrow">一份可以慢慢读的学习路线 / {html.escape(str(catalog.get('updated') or date.today().isoformat()))}</div><h1>{html.escape(catalog['title'])}</h1><p class="lead">{html.escape(catalog['subtitle'])}</p><p>从感兴趣的具体问题出发，按自己的节奏探索。</p><div class="hero-meta"><span>{ready} 篇可读笔记</span><span>{sum(any(e['module'] == m for e in entries) for m in catalog['modules'])} 个主题</span><span>视频回看 · 离线公式 · 关键画面</span></div><p><a href="flow.html">探索学习脉络 →</a></p></section>
<section class="start"><div><div class="eyebrow">先从这里开始</div><h2>从一个问题出发。</h2><p>这些入口聚焦搜索与 Agent，也可以在学习脉络中按兴趣选择其他主题。</p></div><div class="start-links">{starters}</div></section>
{external_section(external)}
<section class="practice"><h2>贯穿课程的一张练习纸</h2><p>选一个你确实想解决的问题，保留原回答，然后写下：</p><ol><li>用户此刻要完成什么？怎样才算完成？</li><li>哪一句话或哪一步出了问题？证据在哪里？</li><li>改动哪个环节？哪些条件保持不变？</li><li>怎样用另一个问题检验，避免只修好这一例？</li></ol><p>AI 生成的示例只能作为练习材料；项目经历、判断和测量结果需要自己完成并如实记录。</p></section>
<nav class="module-nav" aria-label="课程章节">{module_links}</nav>
<div class="tools"><label>找一篇笔记 <input id="course-search" type="search" placeholder="搜索 RAG、数据、调研…"></label><label>阅读范围 <select id="priority"><option value="all">全部内容</option><option value="核心">只看核心</option><option value="补充">通用能力补充</option><option value="拓展">技术与视野拓展</option><option value="unread">尚未学过</option></select></label><span id="progress" aria-live="polite"></span></div><p id="empty" hidden>当前筛选没有结果，试试清空关键词或切回全部内容。</p>
{''.join(groups)}<section class="transfer"><h2>换设备，继续学</h2><p>课程内容通过 GitHub Pages 阅读。进度保存在本机，下面两个按钮可以手动带走；不会上传任何练习答案或浏览记录。</p><button id="export-progress" type="button">导出学习进度</button><label class="button">导入学习进度<input type="file" id="import-progress" accept="application/json,.json" hidden></label><p id="transfer-message" role="status"></p></section></main>'''
    (COURSE / "index.html").write_text(shell(catalog['title'], content), encoding="utf-8", newline="\n")
    (COURSE / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    build_learning_flow.build(COURSE)
    print(f"Course built: {ready}/{len(entries)} readable entries")


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        self.urls.extend(v for k, v in attrs if k in {"src", "href"} and v)


def stage():
    dest = ROOT / ".state/course-site"
    dest.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((COURSE / "catalog.json").read_text(encoding="utf-8"))
    files = {COURSE / p for p in ("catalog.json", "index.json", "external.json", "index.html", "flow.html", "assets/flow.css", "assets/flow.js", "assets/flow-data.js", "assets/reader.css", "assets/reader.js", "assets/frames.json", "assets/vendor/THREE-LICENSE.txt")}
    if (COURSE / "README.md").is_file():
        files.add(COURSE / "README.md")
    for item in catalog["videos"]:
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", item["bvid"]):
            raise ValueError("Invalid catalog video identity")
        files.update(p for ext in ("md", "html") if (p := COURSE / "lessons" / f"{item['bvid']}.{ext}").is_file())
        cover = COURSE / "assets/covers" / f"{item['bvid']}.webp"
        if cover.is_file():
            files.add(cover)
    for item in build_learning_flow.load_external(COURSE):
        cover_path = item.get("cover")
        if cover_path:
            cover = COURSE / cover_path
            if not cover.is_file():
                raise ValueError(f"Missing external video cover: {cover_path}")
            files.add(cover)
    pages = [p for p in files if p.suffix == ".html"]
    for page in pages:
        parser = Links(); parser.feed(page.read_text(encoding="utf-8"))
        for raw in parser.urls:
            if raw == "about:blank" or raw.startswith("#") or urlsplit(raw).scheme in {"http", "https"}:
                continue
            if urlsplit(raw).scheme or raw.startswith("//"):
                raise ValueError(f"Unapproved URL scheme from {page.name}")
            p = (page.parent / unquote(urlsplit(raw).path)).resolve()
            if not any(p.is_relative_to(base.resolve()) for base in (COURSE, ROOT / "notes", ROOT / "assets/fonts")):
                raise ValueError(f"Page references a private/unapproved path: {page.name}")
            if not p.is_file():
                raise ValueError(f"Missing local link from {page.name}: {raw}")
            files.add(p)
    files.update(ROOT / "assets/fonts" / name for name in ("LXGWWenKaiGBScreen.ttf", "OFL-LXGW-WenKai-Screen.txt"))
    allowed = {Path("index.html"), Path(".nojekyll")}
    for p in files:
        rel = p.resolve().relative_to(ROOT.resolve()); allowed.add(rel)
        target = dest / rel; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    # Do not silently ship stale artifacts from a previous build.
    stale = [p for p in dest.rglob("*") if p.is_file() and p.relative_to(dest) not in allowed]
    if stale:
        raise ValueError("Stale files in Pages artifact; inspect and remove these task-local artifacts before publishing.")
    (dest / "index.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=courses/search-quality/"><title>学习笔记</title><a href="courses/search-quality/">进入课程</a></html>', encoding="utf-8")
    (dest / ".nojekyll").touch()
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    if size > 1024**3:
        raise ValueError("Publication exceeds the 1 GiB final-artifact budget.")
    print(f"Pages whitelist: {len(allowed)} files, {size / 1024**2:.2f} MiB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--stage-only", action="store_true"); parser.add_argument("--stage", action="store_true")
    args = parser.parse_args()
    if not args.stage_only:
        build()
    if args.stage_only or args.stage:
        stage()
