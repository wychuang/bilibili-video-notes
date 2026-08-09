from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".flv", ".mov", ".avi"}
SUPPORTED_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}
WEB_URL_PATTERN = re.compile(r'https?://[^\s<>"()\[\]）】》」]+', re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;!)]}，。；！？）》】」"
BVID_PATTERN = re.compile(r"BV[A-Za-z0-9]{10}")


class WorkflowError(RuntimeError):
    """A user-actionable workflow failure."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def extract_bilibili_url(text: str) -> str:
    value = text.strip()
    if not value:
        raise WorkflowError("没有检测到 B 站链接。请先复制单个视频链接。")

    for match in WEB_URL_PATTERN.finditer(value):
        candidate = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower()
        supported_host = any(
            host == allowed or host.endswith("." + allowed) for allowed in SUPPORTED_HOSTS
        )
        if parsed.scheme not in {"http", "https"} or not supported_host:
            continue
        if host == "b23.tv" or host.endswith(".b23.tv"):
            return candidate
        if parsed.path.startswith("/video/"):
            return candidate
        if parsed.path.rstrip("/") == "/list/watchlater":
            bvid_values = parse_qs(parsed.query).get("bvid", [])
            if len(bvid_values) == 1 and BVID_PATTERN.fullmatch(bvid_values[0]):
                return f"https://www.bilibili.com/video/{bvid_values[0]}"

    raise WorkflowError("没有从分享文字中找到 bilibili.com 或 b23.tv 的单视频链接。")


def validate_bilibili_url(url: str) -> str:
    return extract_bilibili_url(url)


def safe_component(value: str, max_length: int = 64) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "未命名")[:max_length].rstrip(" .")


def detect_browser() -> str | None:
    candidates: list[tuple[str, Path]] = []
    local = os.environ.get("LOCALAPPDATA")
    roaming = os.environ.get("APPDATA")
    if local:
        local_path = Path(local)
        candidates.extend(
            [
                ("edge", local_path / "Microsoft/Edge/User Data"),
                ("chrome", local_path / "Google/Chrome/User Data"),
            ]
        )
    if roaming:
        candidates.append(("firefox", Path(roaming) / "Mozilla/Firefox/Profiles"))
    return next((name for name, path in candidates if path.exists()), None)


def _yt_dlp_base() -> list[str]:
    return [sys.executable, "-m", "yt_dlp", "--ignore-config"]


def _cookie_args(browser: str | None) -> list[str]:
    return ["--cookies-from-browser", browser] if browser else []


def _compact_error(completed: subprocess.CompletedProcess[str]) -> str:
    text = (completed.stderr or completed.stdout or "未知错误").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-8:])[-1800:]


def probe_video(url: str, preferred_browser: str | None) -> tuple[dict[str, Any], str | None]:
    return _probe_metadata(url, preferred_browser, include_playlist=False)


def probe_submission(
    url: str,
    preferred_browser: str | None,
) -> tuple[dict[str, Any], str | None]:
    return _probe_metadata(url, preferred_browser, include_playlist=True)


def _probe_metadata(
    url: str,
    preferred_browser: str | None,
    *,
    include_playlist: bool,
) -> tuple[dict[str, Any], str | None]:
    attempts = [preferred_browser, None] if preferred_browser else [None]
    last_error = ""
    for browser in dict.fromkeys(attempts):
        if browser:
            print(f"[来源] 尝试读取 {browser} 登录状态……")
        command = [
            *_yt_dlp_base(),
            "--yes-playlist" if include_playlist else "--no-playlist",
            "--skip-download",
            "--dump-single-json",
            "--no-warnings",
            *_cookie_args(browser),
            url,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        if completed.returncode == 0:
            try:
                return json.loads(completed.stdout), browser
            except json.JSONDecodeError as exc:
                last_error = f"yt-dlp 返回了无法解析的元数据：{exc}"
        else:
            last_error = _compact_error(completed)
            if browser:
                print("[来源] 浏览器登录状态读取失败，回退到公开访问。")
    raise WorkflowError(f"无法读取视频信息。\n{last_error}")


def display_duration(seconds: float | int | None) -> str:
    whole = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _submission_parts(url: str, info: dict[str, Any]) -> list[dict[str, Any]]:
    entries = info.get("entries") or []
    if info.get("_type") != "playlist" or len(entries) <= 1:
        return []
    parts: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        entry_url = str(
            entry.get("webpage_url")
            or entry.get("url")
            or f"https://www.bilibili.com/video/{video_key(url, info)}?p={index}"
        )
        parts.append(
            {
                "index": index,
                "id": entry.get("id") or entry.get("display_id"),
                "title": entry.get("title") or f"第 {index} 集",
                "duration_seconds": float(entry.get("duration") or 0),
                "duration_display": display_duration(entry.get("duration")),
                "url": entry_url,
                "uploader": entry.get("uploader") or entry.get("channel"),
            }
        )
    return parts


def submission_overview(
    url: str,
    *,
    use_browser: bool = True,
) -> dict[str, Any]:
    normalized_url = validate_bilibili_url(url)
    preferred_browser = detect_browser() if use_browser else None
    info, browser = probe_submission(normalized_url, preferred_browser)
    parts = _submission_parts(normalized_url, info)
    if parts:
        collection_title = str(info.get("title") or "")
        for part in parts:
            display_title = str(part["title"])
            if collection_title and display_title.startswith(collection_title):
                display_title = display_title[len(collection_title) :].strip()
            display_title = re.sub(r"^p\d+\s*", "", display_title, flags=re.IGNORECASE).strip()
            part["display_title"] = display_title or f"第 {part['index']} 集"
        uploader = next((part["uploader"] for part in parts if part.get("uploader")), None)
        total_duration = sum(float(part["duration_seconds"]) for part in parts)
        return {
            "ok": True,
            "kind": "collection",
            "title": info.get("title") or "B站视频合集",
            "uploader": uploader or "未知UP主",
            "collection_id": video_key(normalized_url, info),
            "current_part": min(requested_part(normalized_url), len(parts)),
            "part_count": len(parts),
            "total_duration_seconds": round(total_duration, 3),
            "total_duration_display": display_duration(total_duration),
            "parts": parts,
            "browser_session": browser,
            "source_url": normalized_url,
        }

    item = info
    if info.get("_type") == "playlist" and info.get("entries"):
        item = info["entries"][0]
    return {
        "ok": True,
        "kind": "video",
        "title": item.get("title") or "未命名视频",
        "uploader": item.get("uploader") or item.get("channel") or "未知UP主",
        "video_id": video_key(normalized_url, item),
        "duration_seconds": float(item.get("duration") or 0),
        "duration_display": display_duration(item.get("duration")),
        "source_url": normalized_url,
    }


def video_key(url: str, info: dict[str, Any]) -> str:
    candidates = [
        str(info.get("display_id") or ""),
        str(info.get("id") or ""),
        str(info.get("webpage_url") or ""),
        url,
    ]
    joined = " ".join(candidates)
    match = re.search(r"BV[0-9A-Za-z]+", joined, flags=re.IGNORECASE)
    if match:
        return match.group(0)
    av_match = re.search(r"(?:av|AV)(\d+)", joined)
    if av_match:
        return "av" + av_match.group(1)
    return safe_component(str(info.get("id") or "video"), 32)


def requested_part(url: str) -> int:
    values = parse_qs(urlparse(url).query).get("p", ["1"])
    try:
        return max(1, int(values[0]))
    except (TypeError, ValueError):
        return 1


def job_directory(library: Path, url: str, info: dict[str, Any]) -> Path:
    uploader = safe_component(str(info.get("uploader") or info.get("channel") or "未知UP主"), 40)
    title = safe_component(str(info.get("title") or "未命名视频"), 72)
    key = video_key(url, info)
    part = requested_part(url)
    suffix = f"__{key}" + (f"_P{part}" if part > 1 else "")
    return library / uploader / f"{title}{suffix}"


def collection_directory(library: Path, url: str, info: dict[str, Any]) -> Path:
    entries = info.get("entries") or []
    uploader = next(
        (
            str(entry.get("uploader") or entry.get("channel"))
            for entry in entries
            if entry.get("uploader") or entry.get("channel")
        ),
        "未知UP主",
    )
    title = safe_component(str(info.get("title") or "B站视频合集"), 72)
    return library / safe_component(uploader, 40) / f"{title}__{video_key(url, info)}_合集"


def collection_part_directory(
    collection_dir: Path,
    collection_title: str,
    index: int,
    part_title: str,
) -> Path:
    short_title = part_title.strip()
    if short_title.startswith(collection_title):
        short_title = short_title[len(collection_title) :].strip()
    short_title = re.sub(r"^p\d+\s*", "", short_title, flags=re.IGNORECASE).strip()
    return collection_dir / "parts" / f"P{index:02d}_{safe_component(short_title or f'第 {index} 集', 58)}"


def update_status(job_dir: Path, stage: str, **extra: Any) -> None:
    path = job_dir / "status.json"
    status = read_json(path)
    timestamp = now_iso()
    status.setdefault("schema_version", 1)
    status.setdefault("created_at", timestamp)
    status.setdefault("history", [])
    status["stage"] = stage
    status["updated_at"] = timestamp
    status.update(extra)
    status["history"].append({"stage": stage, "at": timestamp})
    write_json(path, status)


def find_source_video(source_dir: Path) -> Path | None:
    if not source_dir.exists():
        return None
    candidates = [
        path
        for path in source_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in VIDEO_EXTENSIONS
        and not path.name.endswith(".part")
    ]
    candidates.sort(key=lambda path: (path.suffix.lower() != ".mp4", -path.stat().st_size))
    return candidates[0] if candidates else None


def download_video(
    url: str,
    source_dir: Path,
    browser: str | None,
) -> Path:
    source_dir.mkdir(parents=True, exist_ok=True)
    existing = find_source_video(source_dir)
    if existing:
        print(f"[下载] 复用已保存视频：{existing.name}")
        return existing

    output_template = str(source_dir / "video.%(ext)s")
    command = [
        *_yt_dlp_base(),
        "--no-playlist",
        "--continue",
        "--no-overwrites",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--concurrent-fragments",
        "1",
        "--sleep-requests",
        "1",
        "--write-info-json",
        "--write-description",
        "--write-thumbnail",
        "--convert-thumbnails",
        "jpg",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "all,-danmaku",
        "--sub-format",
        "srt/best",
        "--convert-subs",
        "srt",
        "--compat-options",
        "no-live-chat",
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "--format",
        "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--output",
        output_template,
        *_cookie_args(browser),
        url,
    ]
    print("[下载] 保存视频、字幕、封面和原始元数据……")
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise WorkflowError("视频下载失败。请查看上方 yt-dlp 输出；已下载的分片会保留用于续传。")

    video_path = find_source_video(source_dir)
    if not video_path:
        raise WorkflowError("下载命令结束后没有找到视频文件。")
    return video_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_source_manifest(
    job_dir: Path,
    video_path: Path,
    url: str,
    info: dict[str, Any],
    browser: str | None,
) -> dict[str, Any]:
    current = read_json(job_dir / "source.json")
    print("[归档] 计算原视频 SHA-256……")
    manifest = {
        "schema_version": 1,
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "video_id": video_key(url, info),
        "requested_part": requested_part(url),
        "source_url": info.get("webpage_url") or url,
        "duration_seconds": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "browser_session": browser,
        "source_file": str(video_path.relative_to(job_dir)).replace("\\", "/"),
        "size_bytes": video_path.stat().st_size,
        "sha256": sha256_file(video_path),
        "downloaded_at": current.get("downloaded_at") or now_iso(),
    }
    write_json(job_dir / "source.json", manifest)
    return manifest


def verify_source(job_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    video_path = job_dir / str(manifest["source_file"])
    current_size = video_path.stat().st_size
    current_hash = sha256_file(video_path)
    verified = current_size == manifest["size_bytes"] and current_hash == manifest["sha256"]
    manifest["verified_at"] = now_iso()
    manifest["verified_unchanged"] = verified
    write_json(job_dir / "source.json", manifest)
    if not verified:
        raise WorkflowError("结束校验发现原视频大小或 SHA-256 已变化。")
    return manifest


def _archive_video(
    url: str,
    strength: str,
    info: dict[str, Any],
    browser: str | None,
    job_dir: Path,
    *,
    archive_only: bool,
) -> dict[str, Any]:
    from .transcript import prepare_transcript, prepare_visual_frames

    job_dir.mkdir(parents=True, exist_ok=True)
    update_status(
        job_dir,
        "probed",
        url=url,
        strength=strength,
        title=info.get("title"),
        error=None,
    )

    try:
        print(f"\n[视频] {info.get('title')}")
        print(f"[作者] {info.get('uploader') or info.get('channel') or '未知'}")
        print(f"[目录] {job_dir}\n")

        update_status(job_dir, "downloading")
        video_path = download_video(url, job_dir / "source", browser)
        manifest = write_source_manifest(job_dir, video_path, url, info, browser)

        update_status(job_dir, "transcribing")
        transcript_meta = prepare_transcript(video_path, job_dir / "source", job_dir / "transcript")
        visual_manifest = prepare_visual_frames(video_path, job_dir / "visual")
        verify_source(job_dir, manifest)
        if archive_only:
            update_status(
                job_dir,
                "completed",
                completed_at=now_iso(),
                archive_only=True,
                transcript_source=transcript_meta.get("source"),
                visual_frame_count=visual_manifest.get("frame_count"),
            )
        return {
            "job_dir": job_dir,
            "manifest": manifest,
            "transcript_meta": transcript_meta,
            "visual_manifest": visual_manifest,
        }
    except Exception as exc:
        update_status(job_dir, "failed", error=str(exc))
        raise


def process_video(
    url: str,
    strength: str,
    library: Path,
    result_file: Path | None = None,
    use_browser: bool = True,
    force_summary: bool = False,
) -> dict[str, Any]:
    from .summary import create_summary, render_summary_html, summary_is_current

    normalized_url = validate_bilibili_url(url)
    preferred_browser = detect_browser() if use_browser else None
    info, browser = probe_video(normalized_url, preferred_browser)
    job_dir = job_directory(library, normalized_url, info)

    try:
        archive = _archive_video(
            normalized_url,
            strength,
            info,
            browser,
            job_dir,
            archive_only=False,
        )
        manifest = archive["manifest"]
        transcript_meta = archive["transcript_meta"]
        visual_manifest = archive["visual_manifest"]

        update_status(
            job_dir,
            "summarizing",
            transcript_source=transcript_meta.get("source"),
            visual_frame_count=visual_manifest.get("frame_count"),
        )
        notes_dir = job_dir / "notes" / strength
        notes_dir.mkdir(parents=True, exist_ok=True)
        summary_path = notes_dir / "summary.md"
        if force_summary or not summary_is_current(summary_path, strength):
            create_summary(job_dir, strength, summary_path)
        else:
            print(f"[总结] 复用已有 {strength} 总结。")

        html_path = render_summary_html(job_dir, strength, summary_path, manifest, transcript_meta)
        update_status(
            job_dir,
            "completed",
            completed_at=now_iso(),
            summary=str(summary_path.relative_to(job_dir)).replace("\\", "/"),
            html=str(html_path.relative_to(job_dir)).replace("\\", "/"),
        )
        result = {
            "ok": True,
            "job_dir": str(job_dir),
            "summary": str(summary_path),
            "html": str(html_path),
            "strength": strength,
        }
        if result_file:
            write_json(result_file, result)
        print(f"\n[完成] 学习页：{html_path}")
        return result
    except Exception as exc:
        update_status(job_dir, "failed", error=str(exc))
        result = {"ok": False, "job_dir": str(job_dir), "error": str(exc)}
        if result_file:
            write_json(result_file, result)
        raise


def process_collection(
    url: str,
    strength: str,
    library: Path,
    result_file: Path | None = None,
    use_browser: bool = True,
    force_summary: bool = False,
) -> dict[str, Any]:
    from .summary import (
        create_collection_summary,
        render_collection_summary_html,
        summary_is_current,
    )

    normalized_url = validate_bilibili_url(url)
    preferred_browser = detect_browser() if use_browser else None
    info, browser = probe_submission(normalized_url, preferred_browser)
    parts = _submission_parts(normalized_url, info)
    if len(parts) <= 1:
        raise WorkflowError("这个链接没有检测到可作为整体处理的多集视频。")

    collection_dir = collection_directory(library, normalized_url, info)
    collection_dir.mkdir(parents=True, exist_ok=True)
    entries = info.get("entries") or []
    collection_title = str(info.get("title") or "B站视频合集")
    collection_id = video_key(normalized_url, info)
    uploader = next((part["uploader"] for part in parts if part.get("uploader")), "未知UP主")
    existing_collection = read_json(collection_dir / "collection.json")
    collection_manifest: dict[str, Any] = {
        "schema_version": 1,
        "title": collection_title,
        "uploader": uploader,
        "collection_id": collection_id,
        "source_url": normalized_url,
        "part_count": len(parts),
        "total_duration_seconds": round(
            sum(float(part["duration_seconds"]) for part in parts), 3
        ),
        "created_at": existing_collection.get("created_at") or now_iso(),
        "updated_at": now_iso(),
        "parts": [],
    }
    for part in parts:
        display_title = str(part["title"])
        if display_title.startswith(collection_title):
            display_title = display_title[len(collection_title) :].strip()
        display_title = re.sub(r"^p\d+\s*", "", display_title, flags=re.IGNORECASE).strip()
        collection_manifest["parts"].append(
            {
                "index": part["index"],
                "id": part["id"],
                "title": part["title"],
                "display_title": display_title or f"第 {part['index']} 集",
                "duration_seconds": part["duration_seconds"],
                "duration_display": part["duration_display"],
                "url": part["url"],
                "status": "pending",
            }
        )
    write_json(collection_dir / "collection.json", collection_manifest)
    update_status(
        collection_dir,
        "probed",
        url=normalized_url,
        strength=strength,
        title=collection_title,
        part_count=len(parts),
        error=None,
    )

    try:
        for index, (part, raw_entry) in enumerate(zip(parts, entries), start=1):
            entry = dict(raw_entry)
            entry.setdefault("uploader", uploader)
            entry_url = str(part["url"])
            existing_job = job_directory(library, entry_url, entry)
            if existing_job.exists() and find_source_video(existing_job / "source"):
                part_dir = existing_job
                print(f"\n[合集 {index}/{len(parts)}] 复用已有单集归档。")
            else:
                part_dir = collection_part_directory(
                    collection_dir,
                    collection_title,
                    index,
                    str(part["title"]),
                )
                print(f"\n[合集 {index}/{len(parts)}] 处理本集。")

            update_status(
                collection_dir,
                "archiving",
                current_part=index,
                current_part_title=part["title"],
            )
            archive = _archive_video(
                entry_url,
                strength,
                entry,
                browser,
                part_dir,
                archive_only=True,
            )
            manifest = archive["manifest"]
            transcript_meta = archive["transcript_meta"]
            visual_manifest = archive["visual_manifest"]
            record = collection_manifest["parts"][index - 1]
            record.update(
                {
                    "status": "completed",
                    "job_dir": Path(os.path.relpath(part_dir, collection_dir)).as_posix(),
                    "source_file": manifest["source_file"],
                    "sha256": manifest["sha256"],
                    "size_bytes": manifest["size_bytes"],
                    "transcript_source": transcript_meta.get("source"),
                    "visual_frame_count": visual_manifest.get("frame_count"),
                }
            )
            collection_manifest["updated_at"] = now_iso()
            write_json(collection_dir / "collection.json", collection_manifest)

        update_status(collection_dir, "summarizing", current_part=None, current_part_title=None)
        notes_dir = collection_dir / "notes" / strength
        notes_dir.mkdir(parents=True, exist_ok=True)
        summary_path = notes_dir / "summary.md"
        if force_summary or not summary_is_current(summary_path, strength):
            create_collection_summary(collection_dir, strength, summary_path)
        else:
            print(f"[总结] 复用已有合集 {strength} 总结。")
        html_path = render_collection_summary_html(
            collection_dir,
            strength,
            summary_path,
            collection_manifest,
        )
        update_status(
            collection_dir,
            "completed",
            completed_at=now_iso(),
            current_part=None,
            current_part_title=None,
            summary=str(summary_path.relative_to(collection_dir)).replace("\\", "/"),
            html=str(html_path.relative_to(collection_dir)).replace("\\", "/"),
        )
        result = {
            "ok": True,
            "kind": "collection",
            "job_dir": str(collection_dir),
            "summary": str(summary_path),
            "html": str(html_path),
            "strength": strength,
            "part_count": len(parts),
        }
        if result_file:
            write_json(result_file, result)
        print(f"\n[完成] 合集学习页：{html_path}")
        return result
    except Exception as exc:
        update_status(collection_dir, "failed", error=str(exc))
        result = {"ok": False, "job_dir": str(collection_dir), "error": str(exc)}
        if result_file:
            write_json(result_file, result)
        raise
