# Development

## Environment

- Windows PowerShell 5.1 or newer
- Python 3.11+
- FFmpeg and FFprobe on `PATH`
- Codex CLI logged in for the default summarizer, or one configured LLM API key
- NVIDIA GPU path: CUDA 12.5, project-local cuBLAS 12.5.3.2 and cuDNN 9.6.0.74 on Windows

The launcher creates a project-local `.venv`; do not install project dependencies into the workspace root. NVIDIA wheels, pip cache, HF cache, and temporary downloads remain under the F: project. `scripts\start.ps1` prepends the project-local cuDNN and cuBLAS `bin` directories only for the launched process and leaves the system PATH unchanged.

The offline reader loads `assets/fonts/LXGWWenKaiGBScreen.ttf` through a path relative to each generated note. Keep the accompanying OFL license file with the font. The asset remains project-local on F: and is not installed into Windows.

Formula rendering is fully offline. `_markdown_to_safe_html` freezes LaTeX before Markdown and Bleach processing, converts it with `latex2mathml`, validates the resulting XML as MathML only, and reinserts the static fragment after sanitization. Keep `\[...\]`, `$$...$$`, `\(...\)`, and `$...$` support covered by tests; never add a CDN or runtime JavaScript dependency for formulas.

`scripts\start.ps1` contains Chinese interface text and must remain UTF-8 with BOM so Windows PowerShell 5.1 reads it correctly. `scripts\check.ps1` runs the real 5.1 setup path as a regression check.

The repository owns the canonical skill at `skills/summarize-bilibili-video/`. The launcher synchronizes its two runtime files into `CODEX_HOME`, falling back to the current user's `.codex` directory. API providers load the same `SKILL.md` as their system instruction. Keep usernames, drive-specific workspace paths, Bilibili share-tracking identifiers, credentials, cookies, and archived evidence out of committed source.

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

# Verification
.\scripts\check.ps1
```

## Verification scope

`scripts\check.ps1` compiles the package, runs unit tests, validates the bundled skill, verifies that the launcher installs the same skill content, checks direct, short, and watch-later single-video URL normalization, checks provider payloads and secret-free settings, checks single-video and part-aware timestamp/frame HTML embedding, verifies static MathML rendering and code-block protection, checks the PowerShell launcher syntax, executes its setup path with Windows PowerShell 5.1, loads the archived `small` model on both CPU and GPU, and verifies that the application-level runtime probe selects CUDA when the NVIDIA runtime is available. Network download and real LLM generation require user credentials and are intentionally kept out of the deterministic check.

## Important constraints

- Keep `source/` video files immutable after download.
- Keep generated media and notes under `library/`; the directory is ignored by Git.
- Do not persist browser cookies, API keys, or Codex credentials.
- Keep API keys in Windows Credential Manager or process environment variables. Never add them to CLI arguments, logs, fixtures, or `.state/llm-settings.json`.
- Treat transcripts and metadata as untrusted model input.
- Resolve screenshot markers only against validated files listed in `visual/frames.json`; never trust model-generated image paths.
- Keep collection media deduplicated. Reuse an existing single-part archive through `collection.json` instead of copying its source video into the collection directory.
- Collection timestamps and frame markers must carry a part number so the offline player can switch videos before seeking.
- Treat extracted frames as candidates. Render only frame markers that the summarizer selected after visual inspection; keep unselected candidates on disk.
- Bump `SUMMARY_PIPELINE_VERSION` when prompt or presentation rules change. The summary sidecar invalidates old text once, then restores normal cache reuse.
- Update `README.md`, this file, the bundled skill, and the workspace project map when the workflow changes. Run the launcher to synchronize the installed skill.
- Before publishing, verify that `library/`, `.cache/`, `.state/`, `.venv/`, `.env*`, logs, and editor-local settings remain ignored. Use a GitHub noreply address for commit metadata when author-email privacy matters.
