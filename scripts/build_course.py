"""Build a dependency-light static reader and a whitelist-only Pages artifact."""
from __future__ import annotations

import argparse
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


def relative(path, base):
    return quote(Path(os.path.relpath(path, base)).as_posix(), safe="/.-_")


def find_reused(item):
    candidates = [f for p in (ROOT / "notes").glob(f"*/*{item['bvid']}*") for f in p.glob("*.md")]
    return max(candidates, key=lambda p: ("合集" in p.parent.name, p.stat().st_size)) if candidates else None


def render(text, source, target, bvid):
    from bili_notes.summary import _markdown_to_safe_html
    figures = []
    registry_path = COURSE / "assets/frames.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []

    def frame_marker(match):
        part, timestamp, caption = match.groups()
        record = next((r for r in registry if r["bvid"] == bvid and r["part"] == int(part or 1) and r["timecode"] == timestamp and r.get("inspected")), None)
        if not record:
            raise ValueError(f"Unreviewed frame marker in {source.name}: {timestamp}")
        path = (COURSE / "assets" / record["file"]).resolve()
        if not path.is_relative_to((COURSE / "assets").resolve()) or not path.is_file():
            raise ValueError("Missing or unsafe reviewed frame")
        href = relative(path, target.parent)
        index = len(figures)
        label = f"[P{record['part']:02d} {timestamp}] {caption}" if part else f"[{timestamp}] {caption}"
        h, m, s = map(int, timestamp.split(":"))
        jump = f"https://www.bilibili.com/video/{bvid}/?t={h*3600+m*60+s}&p={record['part']}"
        figures.append(f'<figure><a href="{href}" target="_blank" rel="noopener"><img src="{href}" alt="{html.escape(caption, quote=True)}" loading="lazy"></a><figcaption><a class="timecode" href="{html.escape(jump, quote=True)}" target="_blank" rel="noopener">{html.escape(label.split("]", 1)[0] + "]")}</a> {html.escape(caption)}</figcaption></figure>')
        return f"\n\nCOURSEFIGURE{index}TOKEN\n\n"

    text = re.sub(r"\[\[FRAME:(?:P(\d+)\|)?(\d{2}:\d{2}:\d{2})\|([^\]\n]+)\]\]", frame_marker, text)

    def freeze_image(match):
        alt, raw = match.groups()
        path = (source.parent / unquote(raw.strip("<>"))).resolve()
        allowed = any(path.is_relative_to(p.resolve()) for p in (ROOT / "notes", COURSE / "assets"))
        if not allowed or not path.is_file() or path.suffix.lower() not in {".jpg", ".png", ".webp"}:
            raise ValueError(f"Unapproved or missing illustration in {source.name}")
        href = relative(path, target.parent)
        index = len(figures)
        figures.append(f'<figure><a href="{href}" target="_blank" rel="noopener"><img src="{href}" alt="{html.escape(alt, quote=True)}" loading="lazy"></a><figcaption>{html.escape(alt)}</figcaption></figure>')
        return f"\n\nCOURSEFIGURE{index}TOKEN\n\n"

    text = re.sub(r"!\[([^\]\n]*)\]\(([^)\n]+)\)", freeze_image, text)
    body, toc = _markdown_to_safe_html(text)
    for i, figure in enumerate(figures):
        body = body.replace(f"<p>COURSEFIGURE{i}TOKEN</p>", figure)

    def time_link(match):
        attrs, label = match.groups()
        seconds = re.search(r'data-seconds="(\d+)"', attrs)
        part = re.search(r'data-part="(\d+)"', attrs)
        url = f"https://www.bilibili.com/video/{bvid}/?t={seconds[1]}" + (f"&p={part[1]}" if part else "")
        return f'<a class="timecode" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" aria-label="在 B 站打开 {html.escape(label, quote=True)}">{label}</a>'

    body = re.sub(r'<button\s+([^>]*data-seconds="\d+"[^>]*)>(.*?)</button>', time_link, body)
    # Relative Markdown links are meaningful only for authored course navigation.
    return body, toc


def shell(title, content, *, lesson=False):
    asset = "../assets" if lesson else "assets"
    home = "../index.html" if lesson else "index.html"
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="description" content="搜索、Agent 与回答质量的中文学习笔记。基于视频证据，保留时间戳、边界和练习。">
<title>{html.escape(title)} · 搜索与 Agent 质量</title><link rel="stylesheet" href="{asset}/reader.css"><script src="{asset}/reader.js" defer></script></head>
<body><a class="skip" href="#main">跳到正文</a><header class="topbar"><a class="brand" href="{home}">问题 / 证据 / 判断</a><span>SEARCH & AGENT FIELDNOTES</span></header>
{content}<footer>个人学习用的批评、比较与重构笔记 · 原视频与截图版权归原作者 · 不提供原视频或完整逐字稿下载<br>笔记离线可读，时间戳链接需联网。学习进度仅存在当前浏览器，可手动导出迁移。</footer></body></html>'''


def build():
    catalog = json.loads((COURSE / "catalog.json").read_text(encoding="utf-8"))
    previous_path = COURSE / "index.json"
    previous = {e["bvid"]: e for e in json.loads(previous_path.read_text(encoding="utf-8"))} if previous_path.exists() else {}
    lessons = COURSE / "lessons"
    lessons.mkdir(exist_ok=True)
    entries = []
    for item in catalog["videos"]:
        bvid = item["bvid"]
        source_path = STATE / bvid / "source.json"
        metadata = json.loads(source_path.read_text(encoding="utf-8")) if source_path.exists() else previous.get(bvid, {})
        source = find_reused(item) if item.get("reuse") else lessons / f"{bvid}.md"
        exists = bool(source and source.exists())
        text = source.read_text(encoding="utf-8") if exists else ""
        title_match = re.search(r"^# (.+)", text)
        title = title_match[1] if title_match else metadata.get("title", bvid)
        record = {k: item[k] for k in ("bvid", "module", "priority", "reason")}
        record.update(title=title, ready=exists, reused=bool(item.get("reuse")), uploader=metadata.get("uploader", ""), duration_seconds=metadata.get("duration_seconds"), parts=len(metadata.get("pages", [])) or metadata.get("parts", 1))
        entries.append(record)
        if not exists:
            continue
        target = lessons / f"{bvid}.html"
        body, toc = render(text, source, target, bvid)
        cover = f'<div class="lesson-top"><a href="../index.html#{item["module"]}">← {html.escape(catalog["modules"][item["module"]])}</a><span>{html.escape(item["priority"])} · {"既有学习稿" if item.get("reuse") else "视频学习笔记"}</span></div>'
        note_meta = "" if item.get("reuse") else f'<div class="provenance">来源：{html.escape(metadata.get("uploader", ""))} · <a href="https://www.bilibili.com/video/{bvid}/" target="_blank" rel="noopener">{bvid} 原视频</a> · 基于本地字幕／转写；自动识别可能有误。正文中的“迁移练习／补充判断”与原视频主张分开标注。</div>'
        content = f'''<main id="main" class="reading-shell"><aside><a href="../index.html">课程目录</a>{toc}<button class="done" data-done="{bvid}" type="button">标记学过</button><p class="aside-note">时间戳打开 B 站。图片可点击查看原尺寸。</p></aside><div>{cover}<article data-lesson="{bvid}">{note_meta}{body}</article><nav class="bottom-nav"><a href="../index.html#{item['module']}">回到本章，继续学习 →</a></nav></div></main>'''
        target.write_text(shell(title, content, lesson=True), encoding="utf-8")
    ready = sum(e["ready"] for e in entries)
    groups = []
    for module, label in catalog["modules"].items():
        cards = []
        for e in [r for r in entries if r["module"] == module]:
            status = "已整理" if e["ready"] else "证据待补 · 暂不冒充总结"
            href = f"lessons/{e['bvid']}.html" if e["ready"] else f"https://www.bilibili.com/video/{e['bvid']}/"
            action = "开始阅读" if e["ready"] else "查看原视频"
            cards.append(f'''<li class="lesson-card" data-priority="{e['priority']}" data-search="{html.escape(e['title']+' '+e['reason'], quote=True)}" data-id="{e['bvid']}"><div class="card-eyebrow"><span>{e['priority']}</span><span>{status}</span></div><h3><a href="{href}">{html.escape(e['title'])}</a></h3><p>{html.escape(e['reason'])}</p><div class="card-bottom"><a href="{href}">{action} ↗</a>{f'<label><input type="checkbox" data-check="{e["bvid"]}"> 学过</label>' if e['ready'] else ''}</div></li>''')
        groups.append(f'<section id="{module}" class="module"><h2>{html.escape(label)}</h2><ul class="lesson-grid">{"".join(cards)}</ul></section>')
    module_links = ''.join(f'<a href="#{m}">{html.escape(n)}</a>' for m, n in catalog['modules'].items())
    starter = [("BV1ojfDBSEPv", "概念地图"), ("BV1YvMy6iE1r", "先定义怎样才算好"), ("BV1Pmux6zEqQ", "把好坏写成标准"), ("BV1MRMnz1EGW", "把标准变成数据"), ("BV1s43z67Ezv", "让信息被理解"), ("BV12suS6rEA8", "用练习检验掌握")]
    starters = ''.join(f'<a href="lessons/{bv}.html"><span>0{i}</span>{label} →</a>' for i, (bv, label) in enumerate(starter, 1) if any(e['bvid'] == bv and e['ready'] for e in entries))
    content = f'''<main id="main" class="home"><section class="hero"><div class="eyebrow">一份可以慢慢读的学习路线 / 2026.09</div><h1>把问题问清楚。<br>把回答看明白。</h1><p class="lead">{html.escape(catalog['subtitle'])}</p><p>从搜索、评测到 Agent 与产品判断；每次只读一篇，再亲手做一个小练习。</p><div class="hero-meta"><span>{ready} 篇可读笔记</span><span>7 个主题</span><span>原文时间戳 · 离线公式 · 关键画面</span></div></section>
<section class="start"><div><div class="eyebrow">先从这里开始</div><h2>不用把目录全学完，<br>先走通这六步。</h2><p>能用自己的话解释，再进入下一篇。扩展内容留在需要时查阅。</p></div><div class="start-links">{starters}</div></section>
<section class="practice"><h2>贯穿课程的一张练习纸</h2><p>选一个你确实想解决的问题，保留原回答，然后写下：</p><ol><li>用户此刻要完成什么？怎样才算完成？</li><li>哪一句话或哪一步出了问题？证据在哪里？</li><li>改动哪个环节？哪些条件保持不变？</li><li>怎样用另一个问题检验，避免只修好这一例？</li></ol><p>AI 生成的示例只能作为练习材料；项目经历、判断和测量结果需要自己完成并如实记录。</p></section>
<nav class="module-nav" aria-label="课程章节">{module_links}</nav>
<div class="tools"><label>找一篇笔记 <input id="course-search" type="search" placeholder="搜索 RAG、数据、调研…"></label><label>阅读范围 <select id="priority"><option value="all">全部内容</option><option value="核心">只看核心</option><option value="补充">通用能力补充</option><option value="拓展">技术与视野拓展</option><option value="unread">尚未学过</option></select></label><span id="progress" aria-live="polite"></span></div><p id="empty" hidden>当前筛选没有结果，试试清空关键词或切回全部内容。</p>
{''.join(groups)}<section class="transfer"><h2>换设备，继续学</h2><p>课程内容通过 GitHub Pages 阅读。进度保存在本机，下面两个按钮可以手动带走；不会上传任何练习答案或浏览记录。</p><button id="export-progress" type="button">导出学习进度</button><label class="button">导入学习进度<input type="file" id="import-progress" accept="application/json,.json" hidden></label><p id="transfer-message" role="status"></p></section></main>'''
    (COURSE / "index.html").write_text(shell(catalog['title'], content), encoding="utf-8")
    (COURSE / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    files = {COURSE / p for p in ("catalog.json", "index.json", "index.html", "assets/reader.css", "assets/reader.js", "assets/frames.json")}
    if (COURSE / "README.md").is_file():
        files.add(COURSE / "README.md")
    for item in catalog["videos"]:
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", item["bvid"]):
            raise ValueError("Invalid catalog video identity")
        files.update(p for ext in ("md", "html") if (p := COURSE / "lessons" / f"{item['bvid']}.{ext}").is_file())
    pages = [p for p in files if p.suffix == ".html"]
    for page in pages:
        parser = Links(); parser.feed(page.read_text(encoding="utf-8"))
        for raw in parser.urls:
            if raw.startswith("#") or urlsplit(raw).scheme in {"http", "https"}:
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
    (dest / "index.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=courses/search-quality/"><title>搜索与 Agent 质量</title><a href="courses/search-quality/">进入课程</a></html>', encoding="utf-8")
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
