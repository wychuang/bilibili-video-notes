from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .workflow import (
    WorkflowError,
    process_collection,
    process_video,
    submission_overview,
    write_json,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="归档并总结一个 B 站视频或多集合集")
    parser.add_argument("--url", required=True, help="bilibili.com 或 b23.tv 视频链接")
    parser.add_argument(
        "--strength",
        choices=["quick", "standard", "deep"],
        default="standard",
        help="总结强度",
    )
    parser.add_argument("--library", type=Path, default=project_root() / "library")
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--no-browser-cookies", action="store_true")
    parser.add_argument("--force-summary", action="store_true")
    parser.add_argument("--probe-only", action="store_true", help="只识别单视频或合集")
    parser.add_argument("--collection", action="store_true", help="将多 P 视频作为一个项目处理")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.probe_only:
            result = submission_overview(args.url, use_browser=not args.no_browser_cookies)
            if args.result_file:
                write_json(args.result_file.resolve(), result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        processor = process_collection if args.collection else process_video
        processor(
            args.url,
            args.strength,
            args.library.resolve(),
            result_file=args.result_file.resolve() if args.result_file else None,
            use_browser=not args.no_browser_cookies,
            force_summary=args.force_summary,
        )
        return 0
    except WorkflowError as exc:
        if args.result_file:
            write_json(args.result_file.resolve(), {"ok": False, "error": str(exc)})
        print(f"\n[失败] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[中止] 用户取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
