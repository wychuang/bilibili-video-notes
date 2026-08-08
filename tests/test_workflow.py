import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from bili_notes.providers import (
    EndpointConfig,
    ProviderClient,
    ProviderError,
    _request_json,
    load_llm_settings,
    save_llm_settings,
)
from bili_notes.summary import (
    _single_api_prompt,
    _write_summary_metadata,
    _markdown_to_safe_html,
    build_prompt,
    render_collection_summary_html,
    render_summary_html,
    summary_is_current,
)
from bili_notes.transcript import (
    _has_cuda_runtime,
    _visual_sample_count,
    choose_subtitle,
    display_time,
    parse_srt,
    srt_time,
    transcribe_video,
)
from bili_notes.workflow import (
    WorkflowError,
    collection_directory,
    collection_part_directory,
    extract_bilibili_url,
    job_directory,
    safe_component,
    submission_overview,
    validate_bilibili_url,
    video_key,
)


class WorkflowTests(unittest.TestCase):
    def test_accepts_bilibili_and_short_links(self):
        self.assertIn("BV1abc", validate_bilibili_url("https://www.bilibili.com/video/BV1abc"))
        self.assertEqual("https://b23.tv/abc", validate_bilibili_url(" https://b23.tv/abc "))

    def test_extracts_url_from_bilibili_share_text(self):
        share_url = (
            "https://www.bilibili.com/video/BV1REDACTED0/"
            "?share_source=copy_web&vd_source=redacted-test-id"
        )
        share_text = f"【示例视频标题】 {share_url}"
        self.assertEqual(share_url, extract_bilibili_url(share_text))
        self.assertEqual("https://b23.tv/abc", extract_bilibili_url("分享：https://b23.tv/abc。"))

    def test_rejects_non_bilibili_url(self):
        with self.assertRaises(WorkflowError):
            validate_bilibili_url("https://example.com/video/BV1abc")

    def test_safe_component_removes_windows_reserved_characters(self):
        self.assertEqual("标题_测试_", safe_component('标题:测试?'))

    def test_video_key_prefers_bv_identifier(self):
        info = {"id": "BV1AbC_p1", "display_id": "BV1AbC"}
        self.assertEqual("BV1AbC", video_key("https://example.invalid", info))

    def test_job_directory_is_stable(self):
        info = {"title": "一条视频", "uploader": "作者", "id": "BV1AbC"}
        path = job_directory(Path("library"), "https://www.bilibili.com/video/BV1AbC", info)
        self.assertEqual(Path("library/作者/一条视频__BV1AbC"), path)

    def test_collection_overview_lists_all_parts_with_short_titles(self):
        info = {
            "_type": "playlist",
            "id": "BV1AbC",
            "title": "一套课",
            "entries": [
                {
                    "id": "BV1AbC_p1",
                    "title": "一套课 p01 开场",
                    "duration": 60,
                    "webpage_url": "https://www.bilibili.com/video/BV1AbC?p=1",
                    "uploader": "作者",
                },
                {
                    "id": "BV1AbC_p2",
                    "title": "一套课 p02 正文",
                    "duration": 120,
                    "webpage_url": "https://www.bilibili.com/video/BV1AbC?p=2",
                    "uploader": "作者",
                },
            ],
        }
        with (
            patch("bili_notes.workflow.detect_browser", return_value=None),
            patch("bili_notes.workflow.probe_submission", return_value=(info, None)),
        ):
            overview = submission_overview("https://www.bilibili.com/video/BV1AbC")
        self.assertEqual("collection", overview["kind"])
        self.assertEqual(2, overview["part_count"])
        self.assertEqual("03:00", overview["total_duration_display"])
        self.assertEqual("正文", overview["parts"][1]["display_title"])

    def test_collection_paths_are_grouped_under_one_project(self):
        info = {
            "id": "BV1AbC",
            "title": "一套课",
            "entries": [{"uploader": "作者"}],
        }
        root = collection_directory(Path("library"), "https://www.bilibili.com/video/BV1AbC", info)
        part = collection_part_directory(root, "一套课", 2, "一套课 p02 正文")
        self.assertEqual(Path("library/作者/一套课__BV1AbC_合集"), root)
        self.assertEqual(root / "parts" / "P02_正文", part)


class TranscriptTests(unittest.TestCase):
    SAMPLE = """1
00:00:01,000 --> 00:00:03,500
第一句话

2
00:01:02,250 --> 00:01:05,000
第二句 <b>重点</b>
"""

    def test_visual_sampling_builds_a_broader_bounded_candidate_pool(self):
        self.assertEqual(1, _visual_sample_count(0.5))
        self.assertEqual(5, _visual_sample_count(5))
        self.assertEqual(8, _visual_sample_count(90))
        self.assertEqual(20, _visual_sample_count(600))
        self.assertEqual(24, _visual_sample_count(3600))

    def test_parse_srt_and_format_times(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.zh-Hans.srt"
            path.write_text(self.SAMPLE, encoding="utf-8")
            segments = parse_srt(path)
        self.assertEqual(2, len(segments))
        self.assertEqual("第二句 重点", segments[1]["text"])
        self.assertEqual("00:01:02", display_time(62.25))
        self.assertEqual("00:01:02,250", srt_time(62.25))

    def test_choose_subtitle_prefers_chinese(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "video.en.srt").write_text("english", encoding="utf-8")
            chinese = root / "video.zh-Hans.srt"
            chinese.write_text("中文", encoding="utf-8")
            (root / "video.danmaku.srt").write_text("弹幕", encoding="utf-8")
            self.assertEqual(chinese, choose_subtitle(root))

    def test_windows_cuda_probe_finds_dll_files_on_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cublas_dir = root / "cublas"
            cudnn_dir = root / "cudnn"
            cublas_dir.mkdir()
            cudnn_dir.mkdir()
            (cublas_dir / "cublas64_12.dll").touch()
            (cudnn_dir / "cudnn64_9.dll").touch()
            runtime_path = os.pathsep.join((str(cublas_dir), str(cudnn_dir)))
            with (
                patch.dict(os.environ, {"PATH": runtime_path}),
                patch("bili_notes.transcript.os.name", "nt"),
                patch("bili_notes.transcript.shutil.which", return_value="nvidia-smi.exe"),
            ):
                self.assertTrue(_has_cuda_runtime())

    def test_no_speech_falls_back_to_visual_evidence(self):
        expected = {"source": "visual-frames", "frame_count": 10}
        with (
            patch("bili_notes.transcript._has_cuda_runtime", return_value=False),
            patch("bili_notes.transcript._transcribe_model", return_value=([], object())),
            patch("bili_notes.transcript.prepare_visual_evidence", return_value=expected) as visual,
        ):
            result = transcribe_video(Path("video.mp4"), Path("transcript"))
        self.assertEqual(expected, result)
        visual.assert_called_once_with(Path("video.mp4"), Path("transcript"))

    def test_first_local_transcription_creates_transcript_directory(self):
        segments = [{"start": 1.0, "end": 2.5, "text": "第一句话"}]
        with tempfile.TemporaryDirectory() as temp:
            transcript_dir = Path(temp) / "new-transcript"
            with (
                patch("bili_notes.transcript._has_cuda_runtime", return_value=False),
                patch("bili_notes.transcript._transcribe_model", return_value=(segments, object())),
            ):
                metadata = transcribe_video(Path("video.mp4"), transcript_dir)
            self.assertEqual("faster-whisper", metadata["source"])
            self.assertTrue((transcript_dir / "transcript.srt").is_file())
            self.assertTrue((transcript_dir / "transcript.txt").is_file())


class SummaryTests(unittest.TestCase):
    def test_summary_cache_tracks_the_bundled_skill_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            summary_path = Path(temp) / "summary.md"
            summary_path.write_text("# 已有总结\n", encoding="utf-8")
            self.assertFalse(summary_is_current(summary_path, "standard"))
            _write_summary_metadata(summary_path, "standard")
            self.assertTrue(summary_is_current(summary_path, "standard"))
            self.assertFalse(summary_is_current(summary_path, "deep"))

    def test_prompt_requests_skill_and_strength(self):
        prompt = build_prompt("standard")
        self.assertIn("$summarize-bilibili-video", prompt)
        self.assertIn("standard", prompt)

    def test_visual_prompt_uses_timestamped_frames(self):
        prompt = build_prompt("standard", "visual-frames")
        self.assertIn("visual/frames.json", prompt)
        self.assertIn("时间戳候选画面", prompt)
        self.assertIn("直接支撑相邻观点", prompt)
        self.assertIn("[[FRAME:HH:MM:SS|", prompt)

    def test_hybrid_prompt_combines_transcript_and_frames(self):
        prompt = build_prompt("standard", "transcript+visual-frames")
        self.assertIn("transcript/transcript.srt", prompt)
        self.assertIn("visual/frames.json", prompt)
        self.assertIn("画面补足", prompt)

    def test_text_only_api_prompt_forbids_frame_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp)
            transcript_dir = job_dir / "transcript"
            transcript_dir.mkdir()
            (job_dir / "source.json").write_text("{}", encoding="utf-8")
            (transcript_dir / "metadata.json").write_text(
                json.dumps({"source": "faster-whisper"}), encoding="utf-8"
            )
            (transcript_dir / "transcript.srt").write_text(
                "1\n00:00:01,000 --> 00:00:02,000\n正文\n", encoding="utf-8"
            )
            prompt = _single_api_prompt(job_dir, "standard")
        self.assertIn("不得输出任何 [[FRAME:...]]", prompt)

    def test_visual_only_api_prompt_requires_codex(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp)
            transcript_dir = job_dir / "transcript"
            transcript_dir.mkdir()
            (job_dir / "source.json").write_text("{}", encoding="utf-8")
            (transcript_dir / "metadata.json").write_text(
                json.dumps({"source": "visual-frames"}), encoding="utf-8"
            )
            with self.assertRaises(WorkflowError):
                _single_api_prompt(job_dir, "standard")

    def test_markdown_renderer_adds_time_button_and_strips_script(self):
        rendered, toc = _markdown_to_safe_html(
            "# 标题\n\n## 第一节\n\n[00:01:02] 内容<script>alert(1)</script>"
        )
        self.assertIn('data-seconds="62"', rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("alert(1)", rendered)
        self.assertIn("第一节", toc)

    def test_markdown_renderer_converts_code_styled_timecode_to_button(self):
        rendered, _ = _markdown_to_safe_html(
            "## 时间戳导航\n\n- `[00:00:13]` 核心概念\n\n覆盖 `[00:00:00]–[00:10:05]`。"
        )
        self.assertIn('class="timecode" data-seconds="13"', rendered)
        self.assertIn('class="timecode" data-seconds="0"', rendered)
        self.assertIn('class="timecode" data-seconds="605"', rendered)
        self.assertNotIn("&lt;button", rendered)
        self.assertNotIn("<code>", rendered)

    def test_markdown_renderer_supports_part_aware_timestamps_and_frames(self):
        frames = [
            {
                "index": 1,
                "part_index": 2,
                "timecode": "00:00:25",
                "timestamp_seconds": 25,
                "relative_path": "../../parts/P02/visual/frame.jpg",
            }
        ]
        rendered, _ = _markdown_to_safe_html(
            "## 跨集证据\n\n[P02 00:00:25] 关键论点。\n\n"
            "[[FRAME:P02|00:00:25|这一页给出核心定义。]]",
            frames,
        )
        self.assertIn('data-part="2" data-seconds="25"', rendered)
        self.assertIn('class="frame-jump" data-part="2"', rendered)
        self.assertIn("这一页给出核心定义。", rendered)

    def test_collection_page_renders_playlist_and_switchable_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            collection_dir = Path(temp) / "library" / "作者" / "合集"
            notes_dir = collection_dir / "notes" / "deep"
            notes_dir.mkdir(parents=True)
            parts = []
            for index in (1, 2):
                job_dir = collection_dir / "parts" / f"P{index:02d}"
                (job_dir / "source").mkdir(parents=True)
                (job_dir / "visual").mkdir()
                (job_dir / "source" / "video.mp4").write_bytes(b"video")
                (job_dir / "visual" / "frame.jpg").write_bytes(b"jpg")
                (job_dir / "source.json").write_text(
                    json.dumps({"source_file": "source/video.mp4"}), encoding="utf-8"
                )
                (job_dir / "visual" / "frames.json").write_text(
                    json.dumps(
                        {
                            "frames": [
                                {
                                    "file": "frame.jpg",
                                    "timecode": "00:00:25",
                                    "timestamp_seconds": 25,
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                parts.append(
                    {
                        "index": index,
                        "title": f"第 {index} 集",
                        "duration_display": "10:00",
                        "status": "completed",
                        "job_dir": f"parts/P{index:02d}",
                    }
                )
            collection = {
                "title": "合集",
                "uploader": "作者",
                "source_url": "https://www.bilibili.com/video/BV1test",
                "parts": parts,
            }
            (collection_dir / "collection.json").write_text(
                json.dumps(collection, ensure_ascii=False), encoding="utf-8"
            )
            summary_path = notes_dir / "summary.md"
            summary_path.write_text(
                "# 合集\n\n## 主线\n\n[P02 00:00:25] 回到第二集。\n",
                encoding="utf-8",
            )
            html_path = render_collection_summary_html(
                collection_dir, "deep", summary_path, collection
            )
            rendered = html_path.read_text(encoding="utf-8")
        self.assertIn("Bilibili Collection Notes", rendered)
        self.assertEqual(2, rendered.count('class="part-button'))
        self.assertIn('data-part="2" data-seconds="25"', rendered)
        self.assertIn("const partVideos", rendered)
        self.assertIn('class="toc-toggle"', rendered)
        self.assertIn("setTocExpanded(false)", rendered)
        self.assertIn('poster="', rendered)

    def test_markdown_renderer_embeds_contextual_visual_evidence(self):
        frames = [
            {
                "index": 1,
                "timecode": "00:00:04",
                "timestamp_seconds": 4.861,
                "relative_path": "../../visual/frame_01.jpg",
            }
        ]
        rendered, _ = _markdown_to_safe_html(
            "## 观察\n\n主内容占据最大面积。\n\n[[FRAME:00:00:04|人物影像承担主视觉。]]",
            frames,
        )
        self.assertIn('class="evidence-figure"', rendered)
        self.assertIn('src="../../visual/frame_01.jpg"', rendered)
        self.assertIn("人物影像承担主视觉。", rendered)
        self.assertNotIn("关键画面图版", rendered)

    def test_markdown_renderer_omits_unreferenced_candidate_frames(self):
        frames = [
            {
                "index": 1,
                "timecode": "00:00:04",
                "timestamp_seconds": 4.861,
                "relative_path": "../../visual/frame_01.jpg",
            }
        ]
        rendered, _ = _markdown_to_safe_html("## 观察\n\n正文。", frames)
        self.assertNotIn("关键画面图版", rendered)
        self.assertNotIn('src="../../visual/frame_01.jpg"', rendered)

    def test_rendered_page_uses_local_wenkai_body_font(self):
        with tempfile.TemporaryDirectory() as temp:
            job_dir = Path(temp) / "job"
            source_dir = job_dir / "source"
            notes_dir = job_dir / "notes" / "standard"
            source_dir.mkdir(parents=True)
            notes_dir.mkdir(parents=True)
            (source_dir / "video.mp4").write_bytes(b"video")
            summary_path = notes_dir / "summary.md"
            summary_path.write_text("# 标题\n\n一段适合长时间阅读的正文。\n", encoding="utf-8")
            html_path = render_summary_html(
                job_dir,
                "standard",
                summary_path,
                {
                    "source_file": "source/video.mp4",
                    "title": "标题",
                    "uploader": "作者",
                    "source_url": "https://www.bilibili.com/video/BV1test",
                },
                {"source": "test"},
            )
            rendered = html_path.read_text(encoding="utf-8")
        self.assertIn('font-family:"Bili WenKai"', rendered)
        self.assertIn("LXGWWenKaiGBScreen.ttf", rendered)
        self.assertIn("font-size:17px", rendered)
        self.assertIn("正文截图：0 张", rendered)


class ProviderTests(unittest.TestCase):
    def test_default_text_provider_remains_codex(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            settings = load_llm_settings(Path(temp))
        self.assertEqual("codex", settings.text.provider)

    def test_saving_deepseek_keeps_secret_out_of_settings_file(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("bili_notes.providers._keyring_set") as keyring_set,
            patch("bili_notes.providers._keyring_get", return_value=""),
            patch.dict(os.environ, {}, clear=True),
        ):
            root = Path(temp)
            save_llm_settings(
                root,
                {
                    "text_provider": "deepseek",
                    "text_model": "deepseek-v4-flash",
                    "text_base_url": "",
                    "text_api_key": "unit-test-secret",
                },
            )
            stored = (root / ".state" / "llm-settings.json").read_text(encoding="utf-8")
        self.assertNotIn("unit-test-secret", stored)
        keyring_set.assert_called_once_with("deepseek", "unit-test-secret")

    def test_deepseek_uses_openai_chat_protocol_without_images(self):
        config = EndpointConfig(
            provider="deepseek",
            label="DeepSeek",
            protocol="openai-chat",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            api_key_env="DEEPSEEK_API_KEY",
        )
        with (
            patch("bili_notes.providers.resolve_api_key", return_value="secret"),
            patch(
                "bili_notes.providers._request_json",
                return_value={"choices": [{"message": {"content": "完成"}}]},
            ) as request_json,
        ):
            result = ProviderClient(config).generate(
                "规则", "证据", max_tokens=1234
            )
        self.assertEqual("完成", result)
        url, _, payload = request_json.call_args.args
        self.assertEqual("https://api.deepseek.com/chat/completions", url)
        self.assertEqual(1234, payload["max_tokens"])
        self.assertEqual({"type": "disabled"}, payload["thinking"])
        self.assertIsInstance(payload["messages"][1]["content"], str)

    def test_gemini_text_adapter_uses_generate_content(self):
        config = EndpointConfig(
            provider="gemini",
            label="Google Gemini",
            protocol="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-3.6-flash",
            api_key_env="GEMINI_API_KEY",
        )
        with (
            patch("bili_notes.providers.resolve_api_key", return_value="secret"),
            patch(
                "bili_notes.providers._request_json",
                return_value={
                    "candidates": [{"content": {"parts": [{"text": "完成"}]}}]
                },
            ) as request_json,
        ):
            result = ProviderClient(config).generate("规则", "证据")
        self.assertEqual("完成", result)
        url, headers, payload = request_json.call_args.args
        self.assertTrue(url.endswith("/models/gemini-3.6-flash:generateContent"))
        self.assertEqual("secret", headers["x-goog-api-key"])
        self.assertEqual("规则", payload["system_instruction"]["parts"][0]["text"])

    def test_anthropic_text_adapter_uses_messages_api(self):
        config = EndpointConfig(
            provider="anthropic",
            label="Anthropic Claude",
            protocol="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-5",
            api_key_env="ANTHROPIC_API_KEY",
        )
        with (
            patch("bili_notes.providers.resolve_api_key", return_value="secret"),
            patch(
                "bili_notes.providers._request_json",
                return_value={"content": [{"type": "text", "text": "完成"}]},
            ) as request_json,
        ):
            result = ProviderClient(config).generate("规则", "证据")
        self.assertEqual("完成", result)
        url, headers, payload = request_json.call_args.args
        self.assertEqual("https://api.anthropic.com/v1/messages", url)
        self.assertEqual("2023-06-01", headers["anthropic-version"])
        self.assertEqual("证据", payload["messages"][0]["content"][0]["text"])

    def test_http_error_redacts_api_key_from_provider_message(self):
        secret = "unit-test-secret-value"
        error = urllib.error.HTTPError(
            "https://example.invalid/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(f"invalid key: {secret}".encode("utf-8")),
        )
        with (
            patch("bili_notes.providers.urllib.request.urlopen", side_effect=error),
            self.assertRaises(ProviderError) as raised,
        ):
            _request_json(
                "https://example.invalid/chat/completions",
                {"Authorization": f"Bearer {secret}"},
                {"model": "test"},
            )
        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
