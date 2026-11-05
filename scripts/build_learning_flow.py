"""Build the public learning map from the course catalog and index."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

COURSE = Path(__file__).resolve().parents[1] / "courses/search-quality"
PATHS = [
    ("ai", "AI 与软件", "#4b9474", "先认识模型，再沿检索、工具调用和评测进入真实软件。", ["map", "search", "evaluate", "agent", "companion", "engineering"]),
    ("product", "产品与设计", "#4b9474", "从人的任务出发，理解产品选择与设计表达。", ["product", "design"]),
    ("research", "研究与知识管理", "#4b9474", "寻找资料、判断证据，并整理可用的知识。", ["research", "knowledge"]),
    ("learning", "学习与职业", "#4b9474", "把学习、实践和职业经验连接起来。", ["learn", "career"]),
    ("life", "经济与生活", "#4b9474", "从具体问题理解经济与日常生活的选择。", ["finance", "home", "wellbeing"]),
    ("culture", "文化与娱乐", "#4b9474", "通过作品、故事和文化内容拓宽视野。", ["culture"]),
]
BRANCHES = {
    "map": ("认识 AI 工具与概念", "先区分模型、工具和运行环境各自的作用。"),
    "search": ("搜索、检索与证据", "观察资料怎样被找到，并检查它能否支持回答。"),
    "evaluate": ("评测、数据与模型", "从具体任务出发，理解评价标准与模型训练。"),
    "agent": ("Agent 的过程与交付", "理解工具调用、上下文与任务执行过程。"),
    "companion": ("桌面助手与日常协作", "从陪伴、记忆和电脑操作，走到多个助手的任务交接。"),
    "engineering": ("软件工程与架构", "通过具体系统理解代码组织与工程选择。"),
    "product": ("用户任务与产品判断", "从用户的问题观察产品选择与交互。"),
    "design": ("设计与表达", "观察信息、形式与使用体验如何联系。"),
    "research": ("调研、信息源与推理", "把问题拆开，寻找并检查相关证据。"),
    "knowledge": ("知识管理", "探索资料整理与知识使用的方法。"),
    "learn": ("学习、表达与实践", "从真实问题出发，用实践和反馈促进理解。"),
    "career": ("职业与成长", "结合具体经历观察职业选择与能力发展。"),
    "finance": ("经济与财务", "理解经济和财务问题中的条件与选择。"),
    "home": ("家庭与日常", "从日常情境出发理解生活中的具体问题。"),
    "wellbeing": ("身心与生活", "了解与身心状态相关的经验和知识。"),
    "culture": ("文化与作品", "按兴趣探索文化、故事和娱乐作品。"),
}
SEQUENCES = {
    "map": "先用一次问答区分 Agent、RAG、MCP 与 Skill；想亲手练习，再读从零使用 AI 的合集。",
    "search": "先看资料该怎样接入，再理解相似度为什么会找错；之后按需进入数据库查询、检索优化和图文回答。",
    "evaluate": "从推荐岗位和咖啡订单判断结果，再读 Rubric 与回归测试；需要理解训练时，再深入数据、后训练和交叉熵。",
    "agent": "先走一遍读取 README 的执行循环，再了解工具可靠性与沙箱；记忆、多助手和视频理解是进一步的专题。",
    "companion": "先决定需要陪伴还是完成工作，再读安装与日常操作；遇到记不住、群聊或电脑操作问题时进入对应细节。",
    "engineering": "先跟着阅读器做出第一版，再用选课程序理解架构；随后进入会话、审查与上线维护。",
    "product": "从厨房中的具体需求开始，再用乐队排练工具练习缩小范围；内容站与办公工具帮助观察长期使用。",
    "design": "先理解注意顺序，再观察留白和视觉张力；网页交互与 AI 设计工具提供具体练习，风格短片留作灵感。",
    "research": "先用一个问题启动调研，再沿关键词和引文寻找资料；因果推理、形式化证明与多角色研究可按需深入。",
    "knowledge": "先理解属性和链接怎样组织笔记，再学习视频笔记与团队经验；个人记忆和文本折叠是不同用途的工具。",
    "learn": "先判断自己是否真正学会，再看摸底、学习路径和练习如何配合；表达方法与中断后的恢复可单独阅读。",
    "career": "从后端实习的学习路线开始，再练习讲清项目；面试、科研和职业取舍分别回答不同阶段的问题。",
    "finance": "先读期权的权利、义务和定价，再检查现金流方案的假设；个人投资复盘、市场历史与事件分析可按兴趣进入。",
    "home": "先看一家人的生活动作怎样变成空间安排，再理解家具报价；显卡行情是一份独立的历史比较案例。",
    "wellbeing": "先从找回一个可选择的小行动开始，再读习惯与社交紧张；成长访谈提供更长的个人经验。",
    "culture": "想读长故事，可从《游戏玩家》的制度寓言开始；想观察表达与创作，接着读情节分析，其余短片随兴趣进入。",
}
SPINE = [{"id": key, "label": label, "description": description, "bvid": bvid} for key, label, description, bvid in [
    ("understand", "弄清 AI 怎么工作", "用一次问答分清模型、工具、检索与 Agent，后面的名词就有了位置。", "BV1ojfDBSEPv"),
    ("question", "说清要解决的问题", "从用户要完成的事出发，判断一个产品究竟帮上了什么忙。", "BV1YvMy6iE1r"),
    ("check", "判断做得好不好", "把模糊的满意与不满意拆成具体标准，理解开放任务怎样评价。", "BV1Pmux6zEqQ"),
]]


EXTERNAL_REQUIRED = {"id", "title", "author", "url", "hacker_tube_url", "summary", "prerequisites", "path", "branch", "cover"}
EXTERNAL_ALLOWED = EXTERNAL_REQUIRED | {"year"}


def load_external(course=COURSE):
    path = course / "external.json"
    if not path.is_file():
        raise ValueError("Missing external watch resources: " + str(path))
    external = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(external, list):
        raise ValueError("External watch resources must be a list")
    seen = set()
    branch_ids = {path_id: set(modules) for path_id, _, _, _, modules in PATHS}
    for item in external:
        if not isinstance(item, dict) or not EXTERNAL_REQUIRED.issubset(item) or set(item) - EXTERNAL_ALLOWED:
            raise ValueError("Invalid external resource schema")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(item["id"])) or item["id"] in seen:
            raise ValueError("Invalid or duplicate external resource id")
        seen.add(item["id"])
        for key in ("title", "author", "summary", "prerequisites"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError("External resource field must be non-empty: " + key)
        for key, hosts in (("url", {"youtube.com", "www.youtube.com"}), ("hacker_tube_url", {"hackertube.org"})):
            parsed = urlsplit(item[key]) if isinstance(item[key], str) else None
            if not parsed or parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
                raise ValueError("Unapproved external resource URL: " + key)
        youtube_id = parse_qs(urlsplit(item["url"]).query).get("v", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", youtube_id):
            raise ValueError("External YouTube URL must contain a video id")
        watch_match = re.fullmatch(r"/watch/([A-Za-z0-9_-]+)", urlsplit(item["hacker_tube_url"]).path)
        if not watch_match or watch_match.group(1) != youtube_id:
            raise ValueError("HackerTube URL must point to a watch page")
        if item["path"] not in branch_ids or item["branch"] not in branch_ids[item["path"]]:
            raise ValueError("Unknown external learning path or branch")
        if not isinstance(item["cover"], str) or (item["cover"] and not re.fullmatch(r"assets/covers/external-[a-z0-9-]+\.webp", item["cover"])):
            raise ValueError("Invalid external resource cover path")
        if item["cover"] and not (course / item["cover"]).is_file():
            raise ValueError("Missing external resource cover: " + item["cover"])
        if "year" in item and (not isinstance(item["year"], int) or not 1900 <= item["year"] <= 2100):
            raise ValueError("Invalid external resource year")
    return external


def make_flow(catalog, index, course=COURSE, external=None):
    indexed = {item["bvid"]: item for item in index}
    modules = {module for *_, modules in PATHS for module in modules}
    unknown = {item["module"] for item in catalog["videos"]} - modules
    if unknown:
        raise ValueError("Unknown learning-flow modules: " + ", ".join(sorted(unknown)))
    paths = []
    for path_id, label, accent, description, module_ids in PATHS:
        branches = []
        for module in module_ids:
            items = [item for item in catalog["videos"] if item["module"] == module]
            if not items:
                continue
            entries = []
            for item in items:
                bv = item["bvid"]
                if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bv):
                    raise ValueError("Invalid catalog video identity")
                record = indexed.get(bv, {})
                ready = bool(record.get("ready") and (course / "lessons" / f"{bv}.html").is_file())
                cover = f"assets/covers/{bv}.webp" if (course / "assets/covers" / f"{bv}.webp").is_file() else ""
                entries.append({"bvid": bv, "title": record.get("title") or bv, "summary": item.get("reason", ""),
                                "duration_seconds": record.get("duration_seconds"), "ready": ready,
                                "href": f"lessons/{bv}.html" if ready else "", "cover": cover,
                                "role": item.get("flow_role") or item.get("priority", "补充")})
            explicit = [item["bvid"] for item in items if item.get("start") and any(e["bvid"] == item["bvid"] and e["ready"] for e in entries)]
            core_ids = {item["bvid"] for item in items if item.get("priority") == "核心"}
            starts = explicit or [e["bvid"] for e in entries if e["ready"] and e["bvid"] in core_ids][:1] or [e["bvid"] for e in entries if e["ready"]][:1]
            branch_label, branch_desc = BRANCHES[module]
            branches.append({"id": module, "label": branch_label, "description": branch_desc,
                             "start_bvids": starts, "sequence_reason": SEQUENCES[module], "lessons": entries})
        paths.append({"id": path_id, "label": label, "color": accent, "description": description, "branches": branches})
    available = {e["bvid"]: e for p in paths for b in p["branches"] for e in b["lessons"]}
    spine = [{**step, **{k: available[step["bvid"]][k] for k in ("href", "cover", "ready", "title")}}
             for step in SPINE if step["bvid"] in available and available[step["bvid"]]["ready"]]
    external = load_external(course) if external is None else external
    return {"updated": catalog.get("updated") or date.today().isoformat(), "spine": spine, "paths": paths, "external": external}


def build(course=COURSE):
    catalog = json.loads((course / "catalog.json").read_text(encoding="utf-8"))
    index = json.loads((course / "index.json").read_text(encoding="utf-8"))
    external = load_external(course)
    flow = make_flow(catalog, index, course, external)
    # Escaping prevents a catalog string from ending the JavaScript statement.
    payload = json.dumps(flow, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    (course / "assets/flow-data.js").write_text("window.LEARNING_FLOW=" + payload + ";\n", encoding="utf-8", newline="\n")
    return flow


if __name__ == "__main__":
    build()
