from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .workflow import WorkflowError, read_json, safe_component, write_json


EXPORT_ENV = "BILI_NOTES_EXPORT_ROOT"
EXPORT_SETTINGS_NAME = "export-settings.json"
STRENGTH_LABELS = {
    "quick": "快览",
    "standard": "标准",
    "deep": "深度",
}
BILIBILI_PUBLIC_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:bilibili\.com|b23\.tv)/[^\s<>)\]\"'，。；、]+",
    re.IGNORECASE,
)


def _sanitize_public_content(content: str) -> str:
    """Remove share tracking data while keeping a useful public source link."""

    def replace_url(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        parsed = urlsplit(raw_url)
        query = parse_qs(parsed.query)
        video_match = re.search(r"/video/(BV[0-9A-Za-z]+)", parsed.path, re.IGNORECASE)
        bvid = video_match.group(1) if video_match else (query.get("bvid") or [""])[0]
        if bvid:
            return f"https://www.bilibili.com/video/{bvid}/"
        host = parsed.netloc.lower()
        if host == "bilibili.com":
            host = "www.bilibili.com"
        return f"https://{host}{parsed.path or '/'}"

    sanitized = BILIBILI_PUBLIC_URL_RE.sub(replace_url, content)
    normalized_lines: list[str] = []
    for line in sanitized.splitlines():
        trimmed = line.rstrip(" \t")
        trailing_width = len(line) - len(trimmed)
        if trimmed and trailing_width >= 2 and not trimmed.endswith("<br>"):
            trimmed += "<br>"
        normalized_lines.append(trimmed)
    return "\n".join(normalized_lines)


def configured_export_root(project_root: Path, override: Path | None = None) -> Path | None:
    value: str | Path | None = override
    if value is None:
        value = os.environ.get(EXPORT_ENV, "").strip() or None
    if value is None:
        settings_path = project_root / ".state" / EXPORT_SETTINGS_NAME
        if settings_path.is_file():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkflowError(f"导出设置损坏：{settings_path}") from exc
            if not isinstance(settings, dict):
                raise WorkflowError("导出设置必须是一个 JSON 对象。")
            stored = settings.get("export_root")
            if stored is not None and not isinstance(stored, str):
                raise WorkflowError("导出设置中的 export_root 必须是路径字符串。")
            value = stored.strip() if isinstance(stored, str) else None
    if value is None or not str(value).strip():
        return None

    expanded = Path(os.path.expandvars(str(value))).expanduser()
    if not expanded.is_absolute():
        expanded = project_root / expanded
    resolved = expanded.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise WorkflowError(f"导出位置已经被同名文件占用：{resolved}")
    return resolved


def _markdown_caption(value: str) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return (compact or "这一帧是相邻观点的直接画面证据。").replace("]", "\\]")


def _frame_export_name(frame: dict[str, Any]) -> str:
    part = int(frame.get("part_index") or 0)
    index = int(frame["index"])
    timecode = str(frame["timecode"]).replace(":", "-")
    suffix = Path(frame["path"]).suffix.lower() or ".jpg"
    prefix = f"p{part:02d}_" if part else ""
    return f"{prefix}frame_{index:03d}_{timecode}{suffix}"


def _project_destination(
    export_root: Path,
    job_dir: Path,
    metadata: dict[str, Any],
    *,
    collection: bool,
) -> Path:
    uploader = safe_component(str(metadata.get("uploader") or "未知UP主"), 40)
    title = safe_component(str(metadata.get("title") or "B站视频学习笔记"), 60)
    identifier = str(
        metadata.get("collection_id" if collection else "video_id")
        or job_dir.name.rsplit("__", 1)[-1]
    )
    suffix = "_合集" if collection else ""
    folder = safe_component(f"{title}__{identifier}{suffix}", 88)
    return export_root / uploader / folder


def _asset_location(
    export_root: Path,
    destination: Path,
    strength: str,
) -> tuple[str, Path, str]:
    export_root = export_root.resolve()
    vault_root = next(
        (
            candidate
            for candidate in (export_root, *export_root.parents)
            if (candidate / ".lightloom").is_dir()
        ),
        None,
    )
    if vault_root is not None:
        project_relative = destination.relative_to(export_root)
        assets_dir = (
            vault_root
            / "derived"
            / "media"
            / "bilibili-video-notes"
            / project_relative
            / strength
        )
        reference = "/" + assets_dir.relative_to(vault_root).as_posix()
        return "lightloom-derived", assets_dir, reference
    assets_relative = Path("assets") / strength
    return "adjacent", destination / assets_relative, assets_relative.as_posix()


def _remove_stale_assets(
    destination: Path,
    manifest_path: Path,
    strength: str,
    asset_mode: str,
    assets_dir: Path,
    current_files: set[str],
) -> None:
    previous = read_json(manifest_path)
    previous_mode = previous.get("asset_mode")
    previous_files = previous.get("asset_files")
    legacy = not isinstance(previous_files, list)
    values = previous.get("assets") if legacy else previous_files
    if previous_mode == "lightloom-derived":
        previous_dir = assets_dir
    elif previous_mode == "adjacent":
        previous_dir = destination / "assets" / strength
    else:
        previous_dir = destination
    previous_root = previous_dir.resolve()
    same_location = previous_mode == asset_mode and not legacy
    for value in values or []:
        if not isinstance(value, str) or (same_location and value in current_files):
            continue
        candidate = (previous_dir / value).resolve()
        if previous_root not in candidate.parents or not candidate.is_file():
            continue
        candidate.unlink()
    for directory in (previous_dir, previous_dir.parent):
        try:
            if directory != destination and directory.is_dir():
                directory.rmdir()
        except OSError:
            pass


def export_summary(
    job_dir: Path,
    strength: str,
    summary_path: Path,
    export_root: Path,
    *,
    collection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .summary import (
        COLLECTION_FRAME_MARKER_RE,
        FRAME_MARKER_RE,
        _collection_visual_frame_records,
        _visual_frame_records,
    )

    if strength not in STRENGTH_LABELS:
        raise WorkflowError(f"未知的总结强度：{strength}")
    if not summary_path.is_file():
        raise WorkflowError(f"找不到要导出的总结：{summary_path}")

    is_collection = collection is not None
    metadata = collection or read_json(job_dir / "source.json")
    if not metadata:
        raise WorkflowError(f"导出所需的来源信息缺失：{job_dir}")
    destination = _project_destination(
        export_root,
        job_dir,
        metadata,
        collection=is_collection,
    )
    destination.mkdir(parents=True, exist_ok=True)

    content = summary_path.read_text(encoding="utf-8")
    visual_frames: list[dict[str, Any]] = []
    if "[[FRAME:" in content:
        visual_frames = (
            _collection_visual_frame_records(job_dir, strength)
            if is_collection
            else _visual_frame_records(job_dir)
        )
    frames_by_key = {
        (int(frame.get("part_index") or 0), str(frame["timecode"])): frame
        for frame in visual_frames
    }
    used: set[tuple[int, str]] = set()
    asset_mode, assets_dir, asset_reference = _asset_location(
        export_root,
        destination,
        strength,
    )
    generated_files: set[str] = set()

    def replace_frame(part: int, timecode: str, caption: str) -> str:
        key = (part, timecode)
        frame = frames_by_key.get(key)
        if frame is None or key in used:
            return ""
        used.add(key)
        assets_dir.mkdir(parents=True, exist_ok=True)
        file_name = _frame_export_name(frame)
        reference_path = f"{asset_reference}/{file_name}"
        shutil.copy2(Path(frame["path"]), assets_dir / file_name)
        generated_files.add(file_name)
        safe_caption = _markdown_caption(caption)
        part_label = f"P{part:02d} · " if part else ""
        figure_label = f"图 {len(used):02d} · {part_label}{timecode}"
        markdown_reference = (
            f"<{reference_path}>" if asset_mode == "lightloom-derived" else reference_path
        )
        return (
            f"\n\n![{figure_label}：{safe_caption}]({markdown_reference})\n\n"
            f"*{figure_label}：{safe_caption}*\n\n"
        )

    content = COLLECTION_FRAME_MARKER_RE.sub(
        lambda match: replace_frame(
            int(match.group(1)),
            match.group(2),
            match.group(3) or "",
        ),
        content,
    )
    content = FRAME_MARKER_RE.sub(
        lambda match: replace_frame(0, match.group(1), match.group(2) or ""),
        content,
    )
    content = _sanitize_public_content(content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"

    label = STRENGTH_LABELS[strength]
    note_path = destination / f"{label}总结.md"
    temp_note = note_path.with_suffix(note_path.suffix + ".tmp")
    temp_note.write_text(content, encoding="utf-8")
    temp_note.replace(note_path)

    manifest_path = destination / f".bili-export-{strength}.json"
    _remove_stale_assets(
        destination,
        manifest_path,
        strength,
        asset_mode,
        assets_dir,
        generated_files,
    )
    write_json(
        manifest_path,
        {
            "schema_version": 2,
            "strength": strength,
            "note": note_path.name,
            "asset_mode": asset_mode,
            "asset_files": sorted(generated_files),
        },
    )
    return {
        "note": note_path,
        "destination": destination,
        "frame_count": len(generated_files),
        "asset_mode": asset_mode,
    }


def export_existing_library(library: Path, export_root: Path) -> list[dict[str, Any]]:
    if not library.is_dir():
        raise WorkflowError(f"本地归档目录不存在：{library}")
    results: list[dict[str, Any]] = []
    for summary_path in sorted(library.rglob("summary.md")):
        notes_dir = summary_path.parent
        if notes_dir.parent.name != "notes":
            continue
        strength = notes_dir.name
        if strength not in STRENGTH_LABELS:
            continue
        job_dir = notes_dir.parent.parent
        collection_path = job_dir / "collection.json"
        collection = read_json(collection_path) if collection_path.is_file() else None
        result = export_summary(
            job_dir,
            strength,
            summary_path,
            export_root,
            collection=collection,
        )
        results.append(result)
        print(f"[导出] {result['note']}")
    return results
