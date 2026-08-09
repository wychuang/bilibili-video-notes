from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .providers import ProviderError, public_settings, save_llm_settings
from .workflow import (
    WorkflowError,
    process_collection,
    process_video,
    submission_overview,
    validate_bilibili_url,
    write_json,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="归档并总结一个 B 站视频或多集合集")
    parser.add_argument("--url", help="bilibili.com 或 b23.tv 视频链接")
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
    parser.add_argument(
        "--normalize-url",
        action="store_true",
        help="提取并输出规范化的单视频地址",
    )
    parser.add_argument("--collection", action="store_true", help="将多 P 视频作为一个项目处理")
    parser.add_argument("--show-llm-settings", action="store_true", help="输出已脱敏的 AI 设置")
    parser.add_argument(
        "--save-llm-settings",
        action="store_true",
        help="从标准输入读取 JSON，并将密钥写入系统凭据库",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.show_llm_settings:
            print(json.dumps(public_settings(project_root()), ensure_ascii=False, indent=2))
            return 0
        if args.save_llm_settings:
            try:
                payload = json.load(sys.stdin)
            except json.JSONDecodeError as exc:
                raise ProviderError("AI 设置不是有效 JSON。") from exc
            if not isinstance(payload, dict):
                raise ProviderError("AI 设置必须是一个 JSON 对象。")
            result = save_llm_settings(project_root(), payload)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.normalize_url:
            input_text = args.url if args.url is not None else sys.stdin.read()
            print(validate_bilibili_url(input_text))
            return 0
        if not args.url:
            raise WorkflowError("请提供 --url，或使用 AI 设置参数。")
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
    except (WorkflowError, ProviderError) as exc:
        if args.result_file:
            write_json(args.result_file.resolve(), {"ok": False, "error": str(exc)})
        print(f"\n[失败] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[中止] 用户取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
