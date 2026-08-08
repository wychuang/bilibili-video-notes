from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .workflow import WorkflowError, now_iso, write_json


TIME_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)


def _time_seconds(value: str) -> float:
    match = TIME_RE.search(value)
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000
    )


def display_time(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d}"


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    return (
        f"{millis // 3_600_000:02d}:"
        f"{(millis % 3_600_000) // 60_000:02d}:"
        f"{(millis % 60_000) // 1000:02d},"
        f"{millis % 1000:03d}"
    )


def parse_srt(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not content:
        return []
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\s*\r?\n", content):
        lines = [line.strip() for line in block.splitlines()]
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            continue
        start_text, end_text = (part.strip() for part in lines[time_index].split("-->", 1))
        try:
            start = _time_seconds(start_text)
            end = _time_seconds(end_text)
        except ValueError:
            continue
        raw_text = " ".join(line for line in lines[time_index + 1 :] if line)
        text = html.unescape(re.sub(r"<[^>]+>", "", raw_text)).strip()
        if text:
            segments.append({"start": start, "end": max(start, end), "text": text})
    return segments


def choose_subtitle(source_dir: Path) -> Path | None:
    candidates = [
        path
        for path in source_dir.glob("*.srt")
        if "danmaku" not in path.name.lower() and "live_chat" not in path.name.lower()
    ]

    def score(path: Path) -> tuple[int, int]:
        name = path.name.lower()
        value = 0
        if any(token in name for token in ("zh-hans", "zh-cn", ".zh.", "chinese")):
            value += 100
        if "ai-zh" in name or "auto" in name:
            value += 80
        if ".en" in name:
            value += 40
        return value, path.stat().st_size

    return max(candidates, key=score) if candidates else None


def _write_transcript_files(
    transcript_dir: Path,
    segments: list[dict[str, Any]],
) -> None:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    text_lines = [f"[{display_time(item['start'])}] {item['text']}" for item in segments]
    (transcript_dir / "transcript.txt").write_text("\n".join(text_lines) + "\n", encoding="utf-8")


def _write_srt(path: Path, segments: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, item in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{srt_time(item['start'])} --> {srt_time(item['end'])}\n{item['text']}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _audit(segments: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [
        max(0.0, current["start"] - previous["end"])
        for previous, current in zip(segments, segments[1:])
    ]
    repeated = sum(
        1
        for previous, current in zip(segments, segments[1:])
        if previous["text"].strip() == current["text"].strip()
    )
    return {
        "segment_count": len(segments),
        "character_count": sum(len(item["text"]) for item in segments),
        "first_speech_second": segments[0]["start"] if segments else None,
        "last_speech_second": segments[-1]["end"] if segments else None,
        "maximum_gap_seconds": round(max(gaps, default=0.0), 2),
        "repeated_neighbor_count": repeated,
    }


def _has_cuda_runtime() -> bool:
    if os.name != "nt":
        return shutil.which("nvidia-smi") is not None
    runtime_files = {"cublas64_12.dll", "cudnn64_9.dll"}
    found_files: set[str] = set()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = entry.strip().strip('"')
        if not directory:
            continue
        for filename in runtime_files - found_files:
            if (Path(directory) / filename).is_file():
                found_files.add(filename)
        if found_files == runtime_files:
            break
    return bool(shutil.which("nvidia-smi") and found_files == runtime_files)


def _transcribe_model(video_path: Path, model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    generator, info = model.transcribe(
        str(video_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=False,
        condition_on_previous_text=True,
        log_progress=True,
    )
    segments = [
        {"start": item.start, "end": item.end, "text": item.text.strip()}
        for item in generator
        if item.text.strip()
    ]
    return segments, info


def prepare_visual_frames(video_path: Path, visual_dir: Path) -> dict[str, Any]:
    manifest_path = visual_dir / "frames.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frames = manifest.get("frames") or []
        if frames and all((visual_dir / str(item.get("file", ""))).exists() for item in frames):
            print("[画面] 复用已有时间戳抽帧。")
            return manifest

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode != 0:
        raise WorkflowError("无法读取视频时长，不能生成画面证据。")
    try:
        duration = float(probe.stdout.strip())
    except ValueError as exc:
        raise WorkflowError("FFprobe 返回了无效的视频时长。") from exc

    frame_count = min(12, max(6, round(duration / 10)))
    timestamps = [duration * (index + 0.5) / frame_count for index in range(frame_count)]
    visual_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps, start=1):
        filename = f"frame_{index:02d}_{display_time(timestamp).replace(':', '')}.jpg"
        frame_path = visual_dir / filename
        completed = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1280,iw)':-2",
                "-q:v",
                "3",
                str(frame_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0 or not frame_path.exists():
            raise WorkflowError(f"提取 {display_time(timestamp)} 画面失败。")
        frames.append(
            {
                "file": filename,
                "timestamp_seconds": round(timestamp, 3),
                "timecode": display_time(timestamp),
            }
        )

    manifest = {
        "source": "timestamped-video-frames",
        "duration_seconds": round(duration, 3),
        "frame_count": len(frames),
        "frames": frames,
    }
    write_json(manifest_path, manifest)
    print(f"[画面] 已提取 {len(frames)} 张带时间戳画面。")
    return manifest


def prepare_visual_evidence(video_path: Path, transcript_dir: Path) -> dict[str, Any]:
    visual_dir = transcript_dir.parent / "visual"
    metadata_path = transcript_dir / "metadata.json"
    audit_path = transcript_dir / "audit.json"
    manifest = prepare_visual_frames(video_path, visual_dir)
    frames = manifest["frames"]
    metadata = {
        "source": "visual-frames",
        "reason": "no-speech-detected",
        "frame_count": len(frames),
        "created_at": now_iso(),
    }
    audit = {
        "evidence_type": "visual-frames",
        "speech_segments": 0,
        "frame_count": len(frames),
        "first_frame_second": frames[0]["timestamp_seconds"],
        "last_frame_second": frames[-1]["timestamp_seconds"],
    }
    transcript_dir.mkdir(parents=True, exist_ok=True)
    write_json(metadata_path, metadata)
    write_json(audit_path, audit)
    print("[画面] 没有检测到人声，将画面作为主要总结证据。")
    return metadata


def transcribe_video(video_path: Path, transcript_dir: Path) -> dict[str, Any]:
    gpu_model = os.environ.get("BILI_NOTES_GPU_MODEL", "turbo")
    cpu_model = os.environ.get("BILI_NOTES_CPU_MODEL", "small")
    attempts = [(gpu_model, "cuda", "float16")] if _has_cuda_runtime() else []
    attempts.append((cpu_model, "cpu", "int8"))
    last_error = ""
    for model_name, device, compute_type in attempts:
        try:
            print(f"[转写] 使用 {model_name} / {device} / {compute_type}……")
            segments, info = _transcribe_model(video_path, model_name, device, compute_type)
            if not segments:
                return prepare_visual_evidence(video_path, transcript_dir)
            _write_srt(transcript_dir / "transcript.srt", segments)
            _write_transcript_files(transcript_dir, segments)
            metadata = {
                "source": "faster-whisper",
                "model": model_name,
                "device": device,
                "compute_type": compute_type,
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "created_at": now_iso(),
            }
            write_json(transcript_dir / "metadata.json", metadata)
            write_json(transcript_dir / "audit.json", _audit(segments))
            return metadata
        except Exception as exc:
            last_error = str(exc)
            if device == "cuda":
                print(f"[转写] GPU 初始化失败，自动回退 CPU：{exc}")
                continue
            break
    raise WorkflowError(f"本地转写失败：{last_error}")


def prepare_transcript(video_path: Path, source_dir: Path, transcript_dir: Path) -> dict[str, Any]:
    existing_meta = transcript_dir / "metadata.json"
    existing_srt = transcript_dir / "transcript.srt"
    existing_text = transcript_dir / "transcript.txt"
    if existing_meta.exists():
        metadata = json.loads(existing_meta.read_text(encoding="utf-8"))
        if metadata.get("source") == "visual-frames":
            manifest_path = transcript_dir.parent / "visual" / "frames.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                frames = manifest.get("frames") or []
                visual_dir = manifest_path.parent
                if frames and all((visual_dir / str(item.get("file", ""))).exists() for item in frames):
                    print("[画面] 复用已有时间戳抽帧。")
                    return metadata
        if existing_srt.exists() and existing_text.exists():
            print("[转写] 复用已有逐字稿。")
            return metadata

    subtitle = choose_subtitle(source_dir)
    if subtitle:
        segments = parse_srt(subtitle)
        if sum(len(item["text"]) for item in segments) >= 20:
            transcript_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(subtitle, transcript_dir / "transcript.srt")
            _write_transcript_files(transcript_dir, segments)
            metadata = {
                "source": "bilibili-subtitle",
                "source_file": subtitle.name,
                "created_at": now_iso(),
            }
            write_json(existing_meta, metadata)
            write_json(transcript_dir / "audit.json", _audit(segments))
            print(f"[转写] 使用 B 站字幕：{subtitle.name}")
            return metadata
        print(f"[转写] 字幕内容过少，改用本地语音识别：{subtitle.name}")

    return transcribe_video(video_path, transcript_dir)
