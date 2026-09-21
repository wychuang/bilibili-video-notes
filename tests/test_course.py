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
PENDING = {"BV1RywNeNEry", "BV1pC4y1P7dR", "BV1h8DYBzErB"}


class CourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((COURSE / "catalog.json").read_text(encoding="utf-8"))
        cls.index = json.loads((COURSE / "index.json").read_text(encoding="utf-8"))

    def test_coverage_and_pending_evidence(self):
        ids = [e["bvid"] for e in self.catalog["videos"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(54, len(ids))
        self.assertEqual(51, sum(e["ready"] for e in self.index))
        self.assertEqual(PENDING, {e["bvid"] for e in self.index if not e["ready"]})
        self.assertEqual(42, len(list((COURSE / "lessons").glob("*.md"))))
        for e in self.index:
            self.assertEqual(e["ready"], (COURSE / "lessons" / f"{e['bvid']}.html").is_file())

    def test_new_notes_have_teaching_core_and_exercise(self):
        for p in (COURSE / "lessons").glob("*.md"):
            text = p.read_text(encoding="utf-8")
            with self.subTest(note=p.name):
                self.assertIn("## 一句话抓住核心", text)
                self.assertIn("练习", text)
                self.assertRegex(text, r"\[(?:P\d+ )?\d{2}:\d{2}:\d{2}\]")
                self.assertGreater(len(text), 700)
                self.assertNotRegex(text, r"不是[^\n。！？]{0,150}而是")

    def test_all_local_links_and_images_resolve(self):
        for p in COURSE.rglob("*.html"):
            parser = builder.Links()
            text = p.read_text(encoding="utf-8")
            ids = re.findall(r'\bid="([^"]+)"', text)
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate DOM ID in {p.name}")
            parser.feed(text)
            for raw in parser.urls:
                parts = urlsplit(raw)
                if parts.scheme in {"https", "http"} or raw.startswith("#"):
                    continue
                with self.subTest(page=p.name, link=raw):
                    self.assertFalse(parts.scheme)
                    target = (p.parent / unquote(parts.path)).resolve()
                    self.assertTrue(target.is_file())
                    self.assertTrue(any(target.is_relative_to(base.resolve()) for base in (COURSE, ROOT / "notes", ROOT / "assets/fonts")))

    def test_timestamps_are_real_links_and_keep_part(self):
        for p in (COURSE / "lessons").glob("*.html"):
            text = p.read_text(encoding="utf-8")
            with self.subTest(note=p.name):
                self.assertNotRegex(text, r"&lt;button[^<]*timecode")
                self.assertNotIn("<button type=\"button\" class=\"timecode\"", text)
                parser = builder.Links(); parser.feed(text)
                timestamps = [u for u in parser.urls if "bilibili.com/video/" in u and "?t=" in u]
                self.assertTrue(timestamps)
                self.assertTrue(all(p.stem in u for u in timestamps))
        memory = (COURSE / "lessons/BV1Vegf6nEag.html").read_text(encoding="utf-8")
        parser = builder.Links(); parser.feed(memory)
        self.assertTrue(any(parse_qs(urlsplit(u).query).get("p") == ["17"] for u in parser.urls))

    def test_math_and_sanitization(self):
        target = COURSE / "lessons/BV1ojfDBSEPv.html"
        text = r"# Test" + "\n\n" + r"\[\dot{\kappa}=r+\kappa^2\]" + "\n\n[00:00:13]\n\n<script>alert(1)</script>"
        result, _ = builder.render(text, target.with_suffix(".md"), target, target.stem)
        self.assertIn("<math", result)
        self.assertNotIn("<script", result)
        self.assertIn("?t=13", result)
        self.assertNotIn("math-fallback", result)
        self.assertIn("<mover>", result)

    def test_uninspected_frame_rejected(self):
        target = COURSE / "lessons/BV1ojfDBSEPv.html"
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            builder.render("[[FRAME:00:00:01|unreviewed]]", target.with_suffix(".md"), target, target.stem)

    def test_all_reviewed_frames_are_used(self):
        frames = json.loads((COURSE / "assets/frames.json").read_text(encoding="utf-8"))
        self.assertEqual(13, len(frames))
        for record in frames:
            self.assertTrue(record["inspected"])
            self.assertTrue((COURSE / "assets" / record["file"]).is_file())
            page = (COURSE / "lessons" / f"{record['bvid']}.html").read_text(encoding="utf-8")
            self.assertIn(record["file"], page)

    def test_public_content_has_no_private_identifiers(self):
        private = re.compile(r"(?:[A-Za-z]:[\\/]Projects[\\/]|C:[\\/]Users[\\/]|file:///|SESSDATA\s*[:=]|bili_jct\s*[:=]|vd_source=|spm_id_from=|watchlater_cfg=|-----BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9]{20,})", re.I)
        for p in COURSE.rglob("*"):
            if p.is_file() and p.suffix in {".md", ".html", ".json", ".css", ".js"}:
                with self.subTest(path=p.name):
                    self.assertIsNone(private.search(p.read_text(encoding="utf-8")))

    def test_stage_allowlist_excludes_unreferenced_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            course = root / "courses/search-quality"
            (course / "assets").mkdir(parents=True)
            (root / "assets/fonts").mkdir(parents=True)
            (course / "catalog.json").write_text('{"videos":[]}', encoding="utf-8")
            for name in ("index.json", "index.html", "assets/reader.css", "assets/reader.js", "assets/frames.json"):
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


if __name__ == "__main__":
    unittest.main()
