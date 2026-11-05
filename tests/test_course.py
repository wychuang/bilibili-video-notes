"""Deterministic public-course checks; no network or private evidence required."""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("course_builder", ROOT / "scripts/build_course.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
COURSE = ROOT / "courses/search-quality"
LEGACY_READY = set("""BV1wydDBDEuC BV1ojfDBSEPv BV1Q3NUetEzV BV1nR376UENq BV1eX5t6rEn7 BV12nRzYPEiK BV1YaGA6wE24 BV1i5H5ejE5r BV1vr421K7od BV1Pmux6zEqQ BV1Hwgj6GEok BV1MRMnz1EGW BV1GN3Z6LE73 BV1vQ3ozPEPB BV1PedUBSEGC BV18Uu36rEbu BV1aW3V6WEsT BV1VPT2zQE2p BV1JsEc6DEdt BV1Vegf6nEag BV1ja95BKE6J BV1dcRqYuECf BV1Rz4iz1Exz BV1WCCnYjEy4 BV1RY7L62Ea1 BV1YvMy6iE1r BV1SM411d7Kp BV1Q7AjzdEQn BV1DAqWYUECX BV16V6iY3EJj BV1fGtFzHEUd BV1s43z67Ezv BV15LKH6PETX BV1bLMX6HE7b BV1pF411f7yD BV1XXk7YUEsS BV1xr6GB5EnH BV11JNn6mESN BV1gZz8BYE3r BV1Wzjg65EM6 BV1sWDFBeERQ BV1GcGX6iEUG BV12suS6rEA8 BV1AfSYBdEPp BV1KXLq64E8V BV177mqBpEqW BV1hubZ6WEfU BV1ST421k7LP BV15cg96BERq BV1Qfg56sEfb BV1XnuH66EzS""".split())


class CourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((COURSE / "catalog.json").read_text(encoding="utf-8"))
        cls.index = json.loads((COURSE / "index.json").read_text(encoding="utf-8"))

    def test_coverage_and_pending_evidence(self):
        ids = [e["bvid"] for e in self.catalog["videos"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {e["bvid"] for e in self.index})
        self.assertTrue(LEGACY_READY.issubset({e["bvid"] for e in self.index if e["ready"]}))
        for e in self.index:
            self.assertEqual(e["ready"], (COURSE / "lessons" / f"{e['bvid']}.html").is_file())

    def test_new_notes_have_substantive_timestamped_content(self):
        for p in (COURSE / "lessons").glob("*.md"):
            text = p.read_text(encoding="utf-8")
            with self.subTest(note=p.name):
                self.assertRegex(text, r"\[(?:P\d+ )?\d{2}:\d{2}:\d{2}\]")
                metadata = next(e for e in self.index if e['bvid'] == p.stem)
                # Brief trailers and visual pieces need an honest guide, not filler.
                self.assertGreater(len(text), 300 if metadata.get('strength') == 'quick' else 700)
                self.assertNotRegex(text, r"不是[^\n。！？]{0,150}而是")
                self.assertNotRegex(text, r"并非[^\n。！？]{0,150}而是")
                self.assertNotRegex(text, r"证据说明|制作说明|字幕纠错|截图挑选|自我验收")
                builder.validate_article(text, metadata)

    def test_all_local_links_and_images_resolve(self):
        for p in COURSE.rglob("*.html"):
            parser = builder.Links()
            text = p.read_text(encoding="utf-8")
            ids = re.findall(r'\bid="([^"]+)"', text)
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate DOM ID in {p.name}")
            parser.feed(text)
            for raw in parser.urls:
                parts = urlsplit(raw)
                if raw == "about:blank" or parts.scheme in {"https", "http"} or raw.startswith("#"):
                    continue
                with self.subTest(page=p.name, link=raw):
                    self.assertFalse(parts.scheme)
                    target = (p.parent / unquote(parts.path)).resolve()
                    self.assertTrue(target.is_file())
                    self.assertTrue(any(target.is_relative_to(base.resolve()) for base in (COURSE, ROOT / "notes", ROOT / "assets/fonts")))

    def test_full_reader_preserves_timestamps_parts_and_course_controls(self):
        for p in (COURSE / "lessons").glob("*.html"):
            text = p.read_text(encoding="utf-8")
            with self.subTest(note=p.name):
                self.assertNotRegex(text, r"&lt;button[^<]*timecode")
                self.assertIn('<button type="button" class="timecode"', text)
                self.assertIn('id="source-online-player"', text)
                self.assertIn(f'bvid={p.stem}', text)
                self.assertIn('id="online-fallback"', text)
                self.assertIn('class="toc-toggle"', text)
                headings = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', text, re.S)
                self.assertTrue(any('总结提炼' in h for h in headings), f'Missing summary section: {p.name}')
                self.assertTrue(any(re.search(r'时间(?:戳)?导航', h) for h in headings), f'Missing time navigation: {p.name}')
                self.assertTrue(any(re.search(r'复习|回看时', h) for h in headings), f'Missing review section: {p.name}')
                self.assertIn(f'data-done="{p.stem}"', text)
                self.assertIn(f'href="{p.stem}.md"', text)
                self.assertNotIn('transcript/', text)
                self.assertNotIn('.state/', text)
        memory = (COURSE / "lessons/BV1Vegf6nEag.html").read_text(encoding="utf-8")
        self.assertRegex(memory, r'class="timecode"[^>]*data-part="17"')
        self.assertEqual(18, memory.count('class="part-button'))

    def test_math_and_sanitization(self):
        target = COURSE / "lessons/BV1ojfDBSEPv.html"
        text = r"# Test" + "\n\n" + r"\[\dot{\kappa}=r+\kappa^2\]" + "\n\n[00:00:13]\n\n<script>alert(1)</script>"
        result, _ = builder.render(text, target.with_suffix(".md"), target, target.stem)
        self.assertIn("<math", result)
        self.assertNotIn("<script", result)
        self.assertIn('data-seconds="13"', result)
        self.assertNotIn("math-fallback", result)
        self.assertIn("<mover>", result)

    def test_uninspected_frame_rejected(self):
        target = COURSE / "lessons/BV1ojfDBSEPv.html"
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            builder.render("[[FRAME:00:00:01|unreviewed]]", target.with_suffix(".md"), target, target.stem)

    def test_all_reviewed_frames_are_used(self):
        frames = json.loads((COURSE / "assets/frames.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(frames), 16)
        for record in frames:
            self.assertTrue(record["inspected"])
            self.assertTrue((COURSE / "assets" / record["file"]).is_file())
            page = (COURSE / "lessons" / f"{record['bvid']}.html").read_text(encoding="utf-8")
            self.assertIn(record["file"], page)

    def test_timestamps_are_bounded_and_collections_require_part(self):
        metadata = {"bvid": "BV1AbCdEfGhJ", "pages": [
            {"part": 1, "duration_seconds": 10}, {"part": 2, "duration_seconds": 20}]}
        builder.validate_article("[P02 00:00:15]", metadata)
        for text in ("[00:00:05]", "[P03 00:00:05]", "[P01 00:00:15]", "[P01 00:60:00]"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                builder.validate_article(text, metadata)

    def test_public_content_has_no_private_identifiers(self):
        private = re.compile(r"(?:[A-Za-z]:[\\/]Projects[\\/]|C:[\\/]Users[\\/]|file:///|SESSDATA\s*[:=]|bili_jct\s*[:=]|vd_source=|spm_id_from=|watchlater_cfg=|-----BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9]{20,})", re.I)
        for p in COURSE.rglob("*"):
            if p.is_file() and p.suffix in {".md", ".html", ".json", ".css", ".js"}:
                with self.subTest(path=p.name):
                    self.assertIsNone(private.search(p.read_text(encoding="utf-8")))

    def test_stage_allowlist_excludes_unreferenced_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".state") as tmp:
            root = Path(tmp)
            course = root / "courses/search-quality"
            (course / "assets").mkdir(parents=True)
            (root / "assets/fonts").mkdir(parents=True)
            (course / "catalog.json").write_text('{"videos":[]}', encoding="utf-8")
            for name in ("index.json", "index.html", "flow.html", "assets/flow.css", "assets/flow.js", "assets/flow-data.js", "assets/reader.css", "assets/reader.js", "assets/frames.json"):
                (course / name).write_text("", encoding="utf-8")
            for name in ("LXGWWenKaiGBScreen.ttf", "OFL-LXGW-WenKai-Screen.txt"):
                (root / "assets/fonts" / name).write_bytes(b"fixture")
            (course / "private-draft.json").write_text("private fixture", encoding="utf-8")
            with patch.object(builder, "ROOT", root), patch.object(builder, "COURSE", course):
                builder.stage()
                self.assertFalse((root / ".state/course-site/courses/search-quality/private-draft.json").exists())
                stray = root / ".state/course-site/stray.txt"
                stray.write_text("not approved", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Stale"):
                    builder.stage()

    def test_learning_flow_uses_catalog_and_safe_existing_assets(self):
        flow = builder.build_learning_flow.make_flow(self.catalog, self.index, COURSE)
        self.assertEqual(["ai", "product", "research", "learning", "life", "culture"], [p["id"] for p in flow["paths"]])
        lessons = [e for p in flow["paths"] for b in p["branches"] for e in b["lessons"]]
        self.assertEqual({e["bvid"] for e in self.catalog["videos"]}, {e["bvid"] for e in lessons})
        for entry in lessons:
            self.assertEqual(bool(entry["href"]), entry["ready"])
            if entry["href"]:
                self.assertEqual(entry["href"], f"lessons/{entry['bvid']}.html")
                self.assertTrue((COURSE / entry["href"]).is_file())
            if entry["cover"]:
                self.assertEqual(entry["cover"], f"assets/covers/{entry['bvid']}.webp")
                self.assertTrue((COURSE / entry["cover"]).is_file())
        for path in flow["paths"]:
            for branch in path["branches"]:
                self.assertTrue(set(branch["start_bvids"]).issubset({e["bvid"] for e in branch["lessons"] if e["ready"]}))

    def test_learning_flow_rejects_unknown_module(self):
        with self.assertRaisesRegex(ValueError, "Unknown learning-flow modules"):
            builder.build_learning_flow.make_flow({"videos": [{"module": "unknown"}]}, [], COURSE)

    def test_strength_prefers_catalog_and_supports_source_blocks(self):
        self.assertEqual("quick", builder.reading_strength({"strength": "quick"}, "> 深度阅读"))
        self.assertEqual("quick", builder.reading_strength({}, "> 阅读强度：快速"))
        self.assertEqual("standard", builder.reading_strength({}, "> 阅读强度：标准"))
        self.assertEqual("deep", builder.reading_strength({}, "> 深度阅读"))


if __name__ == "__main__":
    unittest.main()
