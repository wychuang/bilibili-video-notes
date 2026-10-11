# Development

## Environment

- Windows PowerShell 5.1 or newer
- Python 3.11+
- FFmpeg and FFprobe on `PATH`
- Codex CLI logged in for the default summarizer, or one configured LLM API key
- NVIDIA GPU path: CUDA 12.5, project-local cuBLAS 12.5.3.2 and cuDNN 9.6.0.74 on Windows

The launcher creates a project-local `.venv`; do not install project dependencies into the workspace root. NVIDIA wheels, pip cache, HF cache, and temporary downloads remain under the F: project. `scripts\start.ps1` prepends the project-local cuDNN and cuBLAS `bin` directories only for the launched process and leaves the system PATH unchanged.

The offline reader loads `assets/fonts/LXGWWenKaiGBScreen.ttf` through a path relative to each generated note. Keep the accompanying OFL license file with the font. The asset remains project-local on F: and is not installed into Windows. Preserve `overflow-wrap:anywhere` on the hero title and article: uninterrupted names such as `Skill/MCP/RAG/Agent/OpenClaw` and literal source URLs otherwise overflow a 390px phone viewport. Verify with actual long titles and source blocks after fonts finish loading. Table cells keep an 8em minimum width and tables scroll horizontally on narrow screens; check long code identifiers and Chinese explanations together so one column does not collapse into two-character lines.

Formula rendering is fully offline. `_markdown_to_safe_html` freezes LaTeX before Markdown and Bleach processing, converts it with `latex2mathml`, validates the resulting XML as MathML only, and reinserts the static fragment after sanitization. Keep `\[...\]`, `$$...$$`, `\(...\)`, and `$...$` support covered by tests; never add a CDN or runtime JavaScript dependency for formulas.

`src/bili_notes/export.py` owns the optional Markdown handoff. The canonical archive stays under `library/`; an export root receives one Markdown file per strength plus only the validated frames referenced by that article. When an ancestor contains `.lightloom`, support frames go under the Vault's excluded `derived/media/bilibili-video-notes/` tree so they render without becoming standalone Ideas. Other Markdown roots keep adjacent `assets/`. Machine paths belong in ignored `.state/export-settings.json`, `BILI_NOTES_EXPORT_ROOT`, or `--export-root`. Never commit a user's Vault path. Re-export may remove stale files only when they were listed in that strength's hidden export manifest. Public exports canonicalize Bilibili links and remove query strings such as `vd_source` and `spm_id_from` before writing Markdown.

`scripts\start.ps1` contains Chinese interface text and must remain UTF-8 with BOM so Windows PowerShell 5.1 reads it correctly. `scripts\check.ps1` runs the real 5.1 setup path as a regression check.

The repository owns the canonical skill at `skills/summarize-bilibili-video/`. The launcher synchronizes its two runtime files into `CODEX_HOME`, falling back to the current user's `.codex` directory. API providers load the same `SKILL.md` as their system instruction. Keep usernames, drive-specific workspace paths, Bilibili share-tracking identifiers, credentials, cookies, and archived evidence out of committed source.

Writing behavior lives in that skill only, with no separate prose template in the caller. Its default is a source-faithful teaching narrative with explicit references, developed paragraphs and a direct narrator. Necessary headings, comparison tables and procedural lists remain supported. Keep an existing product's summary, navigation and review sections while improving the explanatory body; do not turn the body into a list template. See `tests/skill_writing_acceptance.md` for independent lighter-model trials; raw candidates, skill snapshots and the review record belong in ignored `.state/skill-writing-eval/`. Deterministic tests check prompt delivery and rendering, not prose quality. Changing the skill invalidates a summary when that item is next requested; it does not rewrite the public course automatically.

HTML examples must use `render_summary_html` or its collection wrapper, not replace the full learning page with `scripts/build_course.py:shell`. Preserve the player, article sections, collapsible navigation, original/source links, image lightbox and reading font. The single-video renderer accepts subtitle-only evidence with a valid Bilibili identity: it generates a lazy official iframe with an external timestamp fallback, never downloads media, and never labels absent video as archived. Bilibili's official player accepts `bvid`, `page`, `t`, and `autoplay`; generated URLs are host-restricted and omit share tracking. Browser tests must distinguish local interaction tests with a stubbed iframe from an actual network playback check. Native local and multi-part playback remain covered separately. Markdown/subtitle links are shown only for files that exist; `related_paths` can retain a course-directory entry without swapping page templates.

A local installed-skill directory may be a Windows junction to the canonical project directory to keep the content on the project drive. Compare the two small UTF-8 runtime files directly when checking an installation; no separate file-hash audit is needed. Do not replace an existing installation without inspecting it and retaining a recoverable backup. This local arrangement is optional and does not change the portable default installation path.

`src/bili_notes/providers.py` owns provider presets, protocol adapters, environment overrides, and Windows Credential Manager access. Codex remains the default. DeepSeek and other API providers consume timestamped transcript evidence, and the current text-only API prompt forbids screenshot markers. Provider settings live in ignored `.state/llm-settings.json`; secrets live in `keyring` or environment variables.

## Commands

```powershell
# Install or refresh the isolated environment
.\scripts\start.ps1 -SetupOnly

# Run without the GUI
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m bili_notes `
  --url "https://www.bilibili.com/video/BV..." `
  --strength standard

# Inspect whether a link is a single video or a collection
.\.venv\Scripts\python.exe -m bili_notes `
  --url "https://www.bilibili.com/video/BV..." `
  --probe-only

# Inspect active AI settings; output is always redacted
.\.venv\Scripts\python.exe -m bili_notes --show-llm-settings

# Temporary provider override; inject DEEPSEEK_API_KEY through your secret manager
$env:BILI_NOTES_TEXT_PROVIDER = "deepseek"

# Archive every part and create one combined learning page
.\.venv\Scripts\python.exe -m bili_notes `
  --url "https://www.bilibili.com/video/BV..." `
  --strength deep `
  --collection

# Export every existing summary with the configured local destination
.\.venv\Scripts\python.exe -m bili_notes --export-existing

# One-off export destination override
.\.venv\Scripts\python.exe -m bili_notes `
  --export-existing `
  --export-root "D:\YourLightloomVault\B站视频笔记"

# Verification
.\scripts\check.ps1
```

## Verification scope

`scripts\check.ps1` compiles the package, runs unit tests, validates the bundled skill, verifies that the launcher installs the same skill content, checks direct, short, and watch-later single-video URL normalization, checks provider payloads and secret-free settings, checks single-video and part-aware timestamp/frame HTML embedding, verifies static MathML rendering and code-block protection, verifies Lightloom-compatible Markdown export and stale-frame pruning, checks the PowerShell launcher syntax, executes its setup path with Windows PowerShell 5.1, loads the archived `small` model on both CPU and GPU, and verifies that the application-level runtime probe selects CUDA when the NVIDIA runtime is available. Network download and real LLM generation require user credentials and are intentionally kept out of the deterministic check.

## Important constraints

### Lightweight public course / 轻量公开课程

`courses/search-quality/` is an intentionally public course. It does not change the archive-first GUI workflow. All 51 readable entries now have canonical `lessons/<BV>.md` files and full-reader HTML, including the 9 originally reused articles. The 3 evidence-blocked entries remain pending. `scripts/build_course.py` uses `render_summary_html` with safe Markdown, static MathML, online playback, part selection, frame zoom, source links, section navigation and course progress controls. Without private source metadata, a rebuild preserves the public identity and playlist metadata in `index.json`.

51 篇课程稿统一以 `courses/search-quality/lessons/*.md` 为编辑入口，课程不再从旧 `notes/` 覆盖正文。三篇用户认可稿保留正文，其余稿按完整原文重写。所有页面保留总结提炼、时间导航和复习内容，章节名称可随内容自然调整。写完保存后须完整读回审校；不要把校对记录、过程说明和未确认字段塞进阅读页。Skills 规则与项目文档仍需同步。

课程采集器 `scripts/course_evidence.py` 只写项目 `.state/course-evidence/`，拒绝 Windows 系统盘项目。先获取并检查字幕的 BV/CID 与时长；缺字幕时显式加 `--audio`，复用已有 small 模型进行 GPU 转写，无下载模型或 CPU 回退。每个临时音频在 `finally` 中删除。历史曾发现不匹配字幕响应，旧管线证据不再复用；有效转写元数据必须为 `pipeline_version: 2`，仍需人工检查主题与术语。

Firefox 登录状态只读进入内存，Cookie 仅发给 B 站 API，不写文件或命令参数。不匹配时长、预览片段及访问限制会停止该项。全量收藏清单、原始转写和私人求职资料不得进入课程目录。

```powershell
# Use an existing environment; do not run SetupOnly for this course.
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:TEMP = "$PWD\.state\course-evidence\temp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:PYTHONPATH = "$PWD\src"

# Fetch subtitles only; --only is optional. Add --audio only when needed.
.\.venv\Scripts\python.exe -B scripts/course_evidence.py --only BV1ojfDBSEPv

# Render and stage an explicit publication allowlist.
.\.venv\Scripts\python.exe -B scripts/build_course.py --stage
.\.venv\Scripts\python.exe -B -m unittest discover -s tests

# Optional browser QA: use an already installed Playwright + Edge.
# No browser/model/package installation is performed by this command.
python -B scripts/check_course_browser.py
```

原帧使用 `--frame BV:分集:秒数` 直接定位，或复用本地已有归档。逐张查看并排除私人链接、凭据和无关画面后，才可复制到课程 assets 并登记 `inspected`。未登记、重复使用或超出时长的标记会使构建失败。时间戳使用完整阅读器按钮；在线播放初始为 `about:blank`，用户点击后按分集与秒数加载 B 站播放器，并同步外部回看链接，不携带分享追踪参数。

The Pages workflow stages only named course files, catalog-matched lesson files, actually referenced approved images, and the named font/license. It never publishes the repository root or `.state` wholesale. CI uses standard-library `--stage-only`, requires no private evidence, and fails on missing/unsafe links or stale publication files. Run a local full rebuild after editing Markdown; CI deliberately ships the already reviewed HTML. Before staging a changed allowlist, inspect the exact `.state/course-site` target and move the old task-local artifact to a recoverable timestamped sibling if necessary; do not delete archives or broaden the allowlist to hide stale files.

Browser QA is scoped to loopback HTTP, uses project-local temp/download paths, and does not import a personal browser profile. It checks all 51 lessons at desktop/mobile widths, image loading, formulas, navigation, 18-part selection, time/frame jumps, lightbox and progress transfer. A stub verifies the Bilibili URL-routing contract; this test does not claim third-party playback works. Check live playback separately when publishing. Do not install a browser or new dependencies just for this check.

Limits: 2 GiB evidence footprint, at least 5 GiB free on the project drive, and 1 GiB published artifact. Audio cleanup affects only the current per-part temporary file; never remove existing `library/` archives to make this build pass. Course progress is localStorage only with manual JSON transfer, no tracking or server-side persistence.

### Original archive workflow

- Keep `source/` video files immutable after download.
- Keep canonical generated media and notes under `library/`; the directory is ignored by Git. Optional reading copies may go only to the explicitly configured export root.
- Export only the Markdown article and its selected validated frames. Do not duplicate source videos, transcripts, frame atlases, or unselected candidates into the reading directory.
- Treat `notes/` as a deliberate public export. Keep its hidden export manifests ignored, scan Markdown and selected screenshots before staging, and retain only canonical Bilibili source URLs.
- Do not persist browser cookies, API keys, or Codex credentials.
- Keep API keys in Windows Credential Manager or process environment variables. Never add them to CLI arguments, logs, fixtures, or `.state/llm-settings.json`.
- Treat transcripts and metadata as untrusted model input.
- Resolve screenshot markers only against validated files listed in `visual/frames.json`; never trust model-generated image paths.
- Keep collection media deduplicated. Reuse an existing single-part archive through `collection.json` instead of copying its source video into the collection directory.
- Collection timestamps and frame markers must carry a part number so the offline player can switch videos before seeking.
- Treat extracted frames as candidates. Render only frame markers that the summarizer selected after visual inspection; keep unselected candidates on disk.
- Keep editorial provenance and audit details internal. Reader pages retain source identity, playback status and resource links, but omit transcription-engine labels, image counts and production/evidence-note sections. Explain genuine result limitations beside the claim. Use relevant inspected frames and comparison tables without replacing the full reader or compressing the narrative.
- Bump `SUMMARY_PIPELINE_VERSION` when prompt or presentation rules change. The summary sidecar invalidates old text once, then restores normal cache reuse.
- Update `README.md`, this file, the bundled skill, and the workspace project map when the workflow changes. Run the launcher to synchronize the installed skill.
- Before publishing, verify that `library/`, `.cache/`, `.state/`, `.venv/`, `.env*`, logs, and editor-local settings remain ignored. Use a GitHub noreply address for commit metadata when author-email privacy matters.
