"""Small-footprint, resumable evidence collection. Raw evidence is never published.

Use an existing Firefox Bilibili session in memory, public subtitle APIs, then
optional audio-only GPU ASR. Every writable path stays under the project on a
non-system drive. No credentials, browser databases or complete videos are copied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state" / "course-evidence"
CATALOG = ROOT / "courses" / "search-quality" / "catalog.json"
API = "https://api.bilibili.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
LIMIT = 2 * 1024**3


def setup():
    if ROOT.drive.casefold() == os.environ.get("SystemDrive", "C:").casefold():
        raise RuntimeError("Move this project off the system drive before collecting evidence.")
    STATE.mkdir(parents=True, exist_ok=True)
    temp = STATE / "temp"
    temp.mkdir(exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(temp)
    for key, rel in {"HF_HOME": ".cache/huggingface", "HUGGINGFACE_HUB_CACHE": ".cache/huggingface/hub", "XDG_CACHE_HOME": ".cache", "PIP_CACHE_DIR": ".cache/pip"}.items():
        os.environ[key] = str(ROOT / rel)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / "src"))
    for name in ("cublas", "cudnn"):
        folder = ROOT / ".venv" / "Lib" / "site-packages" / "nvidia" / name / "bin"
        if folder.exists():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def cookie_header():
    # immutable=1 prevents SQLite journal/shared-memory writes beside the profile.
    profiles = Path(os.environ.get("APPDATA", "")) / "Mozilla/Firefox/Profiles"
    sessions = []
    for db in sorted(profiles.glob("*/cookies.sqlite")):
        try:
            with sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
                rows = conn.execute("SELECT host,name,value,expiry FROM moz_cookies WHERE host='bilibili.com' OR host LIKE '%.bilibili.com'").fetchall()
        except sqlite3.Error:
            continue
        valid = [(name, value) for _, name, value, expiry in rows if not expiry or expiry > time.time()]
        if any(name == "SESSDATA" for name, _ in valid):
            sessions.append(dict(valid))
    identities = {s.get("DedeUserID") for s in sessions}
    if len(identities) > 1:
        raise RuntimeError("Multiple Bilibili accounts found; select a profile before continuing.")
    return "; ".join(f"{k}={v}" for k, v in sessions[0].items()) if sessions else ""


def curl(url, cookie="", output=None, limit=8 * 1024**2):
    host = urllib.parse.urlsplit(url).hostname or ""
    headers = [f"User-Agent: {UA}", "Referer: https://www.bilibili.com/"]
    # Session cookies never go to subtitle/CDN/third-party hosts or CLI arguments.
    if cookie and host == "api.bilibili.com":
        headers.append("Cookie: " + cookie)
    config = "".join('header = "' + h.replace("\\", "\\\\").replace('"', '\\"') + '"\n' for h in headers)
    args = ["curl.exe" if os.name == "nt" else "curl", "-4", "--silent", "--show-error", "--fail", "--connect-timeout", "8", "--max-time", "180" if output else "30", "--retry", "1", "--max-filesize", str(limit), "--config", "-", url]
    if output:
        target = Path(output).resolve()
        if not target.is_relative_to(STATE.resolve()):
            raise RuntimeError("Download target is outside the evidence workspace.")
        args.extend(["--output", str(target)])
    result = subprocess.run(args, input=config.encode("utf-8"), capture_output=True, timeout=400 if output else 80)
    if result.returncode:
        raise RuntimeError(f"HTTP download failed (curl {result.returncode}); URL and cookies omitted.")
    return result.stdout


def api(endpoint, params, cookie):
    data = json.loads(curl(API + endpoint + "?" + urllib.parse.urlencode(params), cookie))
    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili API returned {data.get('code')}; access restrictions are not bypassed.")
    return data["data"]


def store_segments(folder, segments, source, duration):
    from bili_notes.transcript import _write_srt, _write_transcript_files, _audit
    if not segments or sum(len(s["text"]) for s in segments) < 30:
        raise RuntimeError("Insufficient speech evidence.")
    if any(s["start"] < 0 or s["end"] < s["start"] for s in segments) or segments[-1]["end"] > duration + 10:
        raise RuntimeError("Subtitle timing does not match source duration; evidence rejected.")
    trans = folder / "transcript"
    _write_srt(trans / "transcript.srt", segments)
    _write_transcript_files(trans, segments)
    audit = _audit(segments)
    audit.update({"duration_seconds": duration, "last_speech_fraction": round(segments[-1]["end"] / max(duration, 1), 3)})
    write_json(trans / "audit.json", audit)
    write_json(trans / "metadata.json", {"source": source, "pipeline_version": 2, "language": "zh-or-source", "warning": "Automatic subtitles/ASR may contain errors. End-time coverage does not prove transcript accuracy."})
    return audit


def footprint():
    return sum(p.stat().st_size for p in STATE.rglob("*") if p.is_file())


def check_budget(extra=0):
    if footprint() + extra > LIMIT or shutil.disk_usage(ROOT).free < 5 * 1024**3:
        raise RuntimeError("Evidence budget/drive free-space guard reached. No more media will be downloaded.")


def local_jobs(bvid):
    return sorted((ROOT / "library").glob(f"*/*__{bvid}*"), key=lambda p: (not p.name.endswith("_合集"), p.name))


def valid_transcript(folder):
    meta = folder / "transcript/metadata.json"
    return meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("pipeline_version") == 2 and (folder / "transcript/transcript.srt").exists()


def collect(item, cookie):
    bvid = item["bvid"]
    folder = STATE / bvid
    status_path = folder / "status.json"
    if item.get("reuse"):
        jobs = local_jobs(bvid)
        notes = [p for j in jobs for p in j.glob("notes/*/summary.md")]
        if notes:
            write_json(status_path, {"bvid": bvid, "status": "reused", "jobs": [str(j.relative_to(ROOT)) for j in jobs], "notes": [str(n.relative_to(ROOT)) for n in notes]})
            return "reused"
    if status_path.exists():
        old = json.loads(status_path.read_text(encoding="utf-8"))
        if old.get("pipeline_version") == 2 and old.get("status") in {"subtitles_complete", "transcript_complete"}:
            return old["status"]
    view = api("x/web-interface/view", {"bvid": bvid}, cookie)
    public = {"bvid": bvid, "title": view["title"], "uploader": view.get("owner", {}).get("name", ""), "url": f"https://www.bilibili.com/video/{bvid}/", "duration_seconds": view.get("duration"), "published_at": view.get("pubdate"), "pages": [{k: p[k] for k in ("page", "part", "cid", "duration")} for p in view["pages"]]}
    write_json(folder / "source.json", public)
    parts = []
    for part in public["pages"]:
        target = folder / f"p{part['page']:02d}"
        if valid_transcript(target):
            parts.append({"page": part["page"], "status": "ready"})
            continue
        player = api("x/player/wbi/v2", {"bvid": bvid, "cid": part["cid"]}, cookie)
        if player.get("bvid") != bvid or player.get("cid") != part["cid"]:
            raise RuntimeError("Subtitle response identity does not match requested video/part.")
        subs = [s for s in (player.get("subtitle") or {}).get("subtitles", []) if s.get("subtitle_url")]
        subs = sorted(subs, key=lambda s: (0 if s.get("lan") in {"zh-CN", "zh-Hans"} else 1 if "zh" in s.get("lan", "") else 2, bool(s.get("ai_type"))))
        if not subs:
            parts.append({"page": part["page"], "status": "needs_audio"})
            continue
        sub = subs[0]
        url = sub["subtitle_url"]
        if url.startswith("//"):
            url = "https:" + url
        body = json.loads(curl(url))
        segments = [{"start": float(s["from"]), "end": float(s["to"]), "text": str(s["content"]).strip()} for s in body["body"] if str(s.get("content", "")).strip()]
        audit = store_segments(target, segments, "bilibili:x/player/wbi/v2:" + sub["lan"], part["duration"])
        parts.append({"page": part["page"], "status": "ready", "characters": audit["character_count"]})
        time.sleep(0.2)
    status = "subtitles_complete" if all(p["status"] == "ready" for p in parts) else "needs_audio"
    write_json(status_path, {"bvid": bvid, "pipeline_version": 2, "status": status, "parts": parts})
    return status


_MODEL = None


def play_info(bvid, part, cookie):
    from yt_dlp.extractor.bilibili import BilibiliBaseIE
    class Signer(BilibiliBaseIE):
        def _download_json(self, url, video_id, **kwargs):
            return json.loads(curl(url, cookie))
    params = Signer()._sign_wbi({"bvid": bvid, "cid": part["cid"], "fnval": 4048, "qn": 32, "fourk": 0}, bvid)
    play = api("x/player/wbi/playurl", params, cookie)
    seconds = (play.get("timelength") or 0) / 1000
    if play.get("is_preview") or abs(seconds - part["duration"]) > max(10, part["duration"] * 0.02):
        raise RuntimeError("Media duration/preview does not match source; access limitations are not bypassed.")
    return play


def transcribe(item, cookie):
    global _MODEL
    from faster_whisper import WhisperModel
    bvid = item["bvid"]
    folder = STATE / bvid
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    for part in source["pages"]:
        target = folder / f"p{part['page']:02d}"
        if valid_transcript(target):
            continue
        target.mkdir(parents=True, exist_ok=True)
        play = play_info(bvid, part, cookie)
        audio = (play.get("dash") or {}).get("audio") or []
        stream = min(audio, key=lambda a: a.get("bandwidth", 0)) if audio else None
        estimate = int(part["duration"] * (stream or {}).get("bandwidth", 192000) / 8 * 1.15)
        check_budget(estimate)
        path = target / "temporary-audio.m4a"
        try:
            if stream:
                curl(stream.get("baseUrl") or stream["base_url"], output=path, limit=min(512 * 1024**2, LIMIT - footprint()))
            else:
                progressive = play.get("durl") or []
                if len(progressive) != 1:
                    raise RuntimeError("Separate audio or a single full progressive stream is required.")
                command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rw_timeout", "20000000", "-headers", f"Referer: https://www.bilibili.com/\r\nUser-Agent: {UA}\r\n", "-i", progressive[0]["url"], "-map", "0:a:0", "-vn", "-c:a", "copy", "-t", str(part["duration"] + 3), "-fs", str(min(512 * 1024**2, LIMIT - footprint())), "-y", str(path)]
                result = subprocess.run(command, capture_output=True, timeout=480)
                if result.returncode:
                    raise RuntimeError("Audio extraction from accessible progressive stream failed.")
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, check=True)
            actual = float(json.loads(probe.stdout)["format"]["duration"])
            if abs(actual - part["duration"]) > max(10, part["duration"] * 0.02):
                raise RuntimeError("Downloaded audio duration mismatch; transcription not started.")
            if _MODEL is None:
                model_path = ROOT / ".cache/models/faster-whisper-small"
                if not model_path.exists():
                    raise RuntimeError("Existing small model missing; model download is disabled.")
                _MODEL = WhisperModel(str(model_path), device="cuda", compute_type="float16", local_files_only=True)
            print(f"ASR {bvid} P{part['page']:02d}: cuda / float16", flush=True)
            generator, info = _MODEL.transcribe(str(path), beam_size=5, vad_filter=True, condition_on_previous_text=False)
            segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in generator if s.text.strip()]
            store_segments(target, segments, "faster-whisper-small:cuda-float16", part["duration"])
        finally:
            # This exact per-run file is the only media file removed here.
            if path.exists() and path.resolve().is_relative_to(STATE.resolve()):
                size = path.stat().st_size
                path.unlink()
                print(f"temporary audio removed: {size} bytes", flush=True)
    status["status"] = "transcript_complete"
    status["parts"] = [{"page": p["page"], "status": "ready"} for p in source["pages"]]
    write_json(folder / "status.json", status)
    return status["status"]


def frame(request, cookie):
    bvid, page, second = request.split(":")
    page, second = int(page), int(second)
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
        raise ValueError("Invalid video identity")
    source = json.loads((STATE / bvid / "source.json").read_text(encoding="utf-8"))
    part = next(p for p in source["pages"] if p["page"] == page)
    if not 0 <= second < part["duration"]:
        raise ValueError("Frame is outside the source duration")
    play = play_info(bvid, part, cookie)
    streams = (play.get("dash") or {}).get("video") or []
    if not streams:
        raise RuntimeError("No accessible video stream; no screenshot fabricated.")
    # Prefer legible 720p or lower AVC, seek directly over HTTP; no full video saved.
    preferred = [s for s in streams if s.get("codecid") == 7 and 480 <= s.get("height", 0) <= 720]
    stream = max(preferred, key=lambda s: s.get("height", 0)) if preferred else min(streams, key=lambda s: s.get("bandwidth", 0))
    target = STATE / bvid / f"p{page:02d}" / "frames" / f"{second:05d}.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    check_budget(2 * 1024**2)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-rw_timeout", "20000000", "-headers", f"Referer: https://www.bilibili.com/\r\nUser-Agent: {UA}\r\n", "-ss", str(second), "-i", stream.get("baseUrl") or stream["base_url"], "-frames:v", "1", "-an", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", "-y", str(target)]
    result = subprocess.run(command, capture_output=True, timeout=80)
    if result.returncode or not target.exists():
        raise RuntimeError("Remote frame extraction failed; signed media URL omitted.")
    print(f"frame {bvid} P{page:02d} {second}s ({target.stat().st_size} bytes)", flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--frame", action="append", default=[])
    args = parser.parse_args()
    setup()
    cookie = cookie_header()
    if args.frame:
        for request in args.frame:
            try:
                frame(request, cookie)
            except Exception as exc:
                print(f"frame {request}: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
        return
    entries = json.loads(CATALOG.read_text(encoding="utf-8"))["videos"]
    for index, item in enumerate(entries, 1):
        if args.only and item["bvid"] not in args.only:
            continue
        check_budget()
        try:
            result = collect(item, cookie)
            if result == "needs_audio" and args.audio:
                result = transcribe(item, cookie)
            print(f"{index}/{len(entries)} {item['bvid']} {result}", flush=True)
        except Exception as exc:
            error = {"bvid": item["bvid"], "status": "error", "error": str(exc)[:250]}
            write_json(STATE / item["bvid"] / "error.json", error)
            print(json.dumps(error, ensure_ascii=False), flush=True)
        time.sleep(0.35)
    print(f"Evidence footprint: {footprint() / 1024**2:.2f} MiB", flush=True)


if __name__ == "__main__":
    main()
