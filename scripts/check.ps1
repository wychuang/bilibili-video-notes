$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    & (Join-Path $PSScriptRoot "start.ps1") -SetupOnly
    if ($LASTEXITCODE -ne 0) { throw "环境准备失败。" }
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
Set-Location $projectRoot

Write-Host "[1/8] Python 编译检查"
& $venvPython -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { throw "Python 编译检查失败。" }

Write-Host "[2/8] 单元测试"
& $venvPython -m unittest discover -s tests -p "test*.py"
if ($LASTEXITCODE -ne 0) { throw "单元测试失败。" }

Write-Host "[3/8] Skill 结构验证"
$resolvedCodexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    Join-Path $env:USERPROFILE ".codex"
} else {
    $env:CODEX_HOME
}
$validator = Join-Path $resolvedCodexHome "skills\.system\skill-creator\scripts\quick_validate.py"
$skillDir = Join-Path $projectRoot "skills\summarize-bilibili-video"
if (-not (Test-Path -LiteralPath $validator)) {
    throw "没有找到 Codex skill 验证器：$validator"
}
if (-not (Test-Path -LiteralPath $skillDir)) {
    throw "没有找到 summarize-bilibili-video skill：$skillDir"
}
$previousPythonUtf8 = $env:PYTHONUTF8
$env:PYTHONUTF8 = "1"
& $venvPython $validator $skillDir
$env:PYTHONUTF8 = $previousPythonUtf8
if ($LASTEXITCODE -ne 0) { throw "Skill 验证失败。" }

Write-Host "[4/8] PowerShell 语法检查"
$tokens = $null
$syntaxErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot "start.ps1"),
    [ref]$tokens,
    [ref]$syntaxErrors
) | Out-Null
if ($syntaxErrors.Count -gt 0) {
    $syntaxText = $syntaxErrors | ForEach-Object { $_.Message }
    throw ($syntaxText -join "`n")
}

Write-Host "[5/8] Windows PowerShell 5.1 启动兼容检查"
$windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
& $windowsPowerShell -NoLogo -NoProfile -Sta -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start.ps1") -SetupOnly
if ($LASTEXITCODE -ne 0) { throw "Windows PowerShell 5.1 无法运行启动器。" }
$installedSkill = Join-Path $resolvedCodexHome "skills\summarize-bilibili-video\SKILL.md"
$bundledSkill = Join-Path $skillDir "SKILL.md"
if (-not (Test-Path -LiteralPath $installedSkill)) { throw "启动器没有安装项目内置 skill。" }
if ((Get-FileHash -Algorithm SHA256 $installedSkill).Hash -ne (Get-FileHash -Algorithm SHA256 $bundledSkill).Hash) {
    throw "已安装 skill 与项目内置版本不一致。"
}

Write-Host "[6/8] 本地转写运行库检查"
$localModel = Join-Path $projectRoot ".cache\models\faster-whisper-small"
if (Test-Path (Join-Path $localModel "model.bin")) {
    $previousHfHome = $env:HF_HOME
    $env:HF_HOME = Join-Path $projectRoot ".cache\huggingface"
    $nvidiaRoot = Join-Path $projectRoot ".venv\Lib\site-packages\nvidia"
    $runtimeBins = @(
        (Join-Path $nvidiaRoot "cudnn\bin"),
        (Join-Path $nvidiaRoot "cublas\bin")
    )
    $runtimeBins = @($runtimeBins | Where-Object { Test-Path -LiteralPath $_ })
    if ($runtimeBins.Count -gt 0) {
        $env:PATH = ($runtimeBins -join [System.IO.Path]::PathSeparator) + [System.IO.Path]::PathSeparator + $env:PATH
    }
    & $venvPython -X faulthandler -c "from faster_whisper import WhisperModel; import sys; WhisperModel(sys.argv[1], device='cpu', compute_type='int8'); print('MODEL_LOAD_OK')" $localModel
    $modelLoadExitCode = $LASTEXITCODE
    if ($modelLoadExitCode -ne 0) { throw "本地转写模型加载失败，退出码：$modelLoadExitCode" }
    $cublasDll = @(where.exe cublas64_12.dll 2>$null)
    $cudnnDll = @(where.exe cudnn64_9.dll 2>$null)
    if ((Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) -and $cublasDll.Count -gt 0 -and $cudnnDll.Count -gt 0) {
        & $venvPython -X faulthandler -c "from faster_whisper import WhisperModel; import sys; WhisperModel(sys.argv[1], device='cuda', compute_type='float16'); print('GPU_MODEL_LOAD_OK')" $localModel
        if ($LASTEXITCODE -ne 0) { throw "GPU 转写模型加载失败，退出码：$LASTEXITCODE" }
        & $venvPython -c "from bili_notes.transcript import _has_cuda_runtime; assert _has_cuda_runtime(); print('GPU_RUNTIME_PROBE_OK')"
        if ($LASTEXITCODE -ne 0) { throw "应用没有识别到 GPU 运行库，退出码：$LASTEXITCODE" }
    } else {
        Write-Host "GPU 运行库不完整，跳过 GPU 加载检查。"
    }
    $env:HF_HOME = $previousHfHome
} else {
    Write-Host "本地模型尚未下载，跳过运行库加载检查。"
}

Write-Host "[7/8] B 站分享文字提取检查"
$shareUrl = "https://www.bilibili.com/video/BV1REDACTED0/?share_source=copy_web&vd_source=redacted-test-id"
$shareText = "【示例视频标题】 " + $shareUrl
$resolvedUrl = & $windowsPowerShell -NoLogo -NoProfile -Sta -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start.ps1") -TestUrlInput $shareText
if ($LASTEXITCODE -ne 0 -or $resolvedUrl -ne $shareUrl) { throw "启动器无法从 B 站分享文字中提取视频链接。" }

Write-Host "[8/8] 禁用措辞检查"
$badText = rg -n "不是.+而是" README.md DEVELOPMENT.md src tests scripts\start.ps1 skills 2>$null
if ($LASTEXITCODE -eq 0) { throw "发现工作区禁止的措辞：`n$badText" }

Write-Host "全部检查通过。" -ForegroundColor Green
exit 0
