param(
    [switch]$SetupOnly,
    [AllowEmptyString()][string]$TestUrlInput
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $projectRoot "requirements.txt"
$stateDir = Join-Path $projectRoot ".state"
$resultFile = Join-Path $stateDir "last-result.json"
$probeResultFile = Join-Path $stateDir "last-probe.json"

function Require-Command {
    param([string]$Name, [string]$Message)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw $Message
    }
}

function Add-ProjectGpuRuntimeToPath {
    $nvidiaRoot = Join-Path $projectRoot ".venv\Lib\site-packages\nvidia"
    $runtimeBins = @(
        (Join-Path $nvidiaRoot "cudnn\bin"),
        (Join-Path $nvidiaRoot "cublas\bin")
    )
    $runtimeBins = @($runtimeBins | Where-Object { Test-Path -LiteralPath $_ })
    if ($runtimeBins.Count -gt 0) {
        $env:PATH = ($runtimeBins -join [System.IO.Path]::PathSeparator) + [System.IO.Path]::PathSeparator + $env:PATH
    }
}

function Sync-BundledSkill {
    $bundledSkillDir = Join-Path $projectRoot "skills\summarize-bilibili-video"
    if (-not (Test-Path -LiteralPath (Join-Path $bundledSkillDir "SKILL.md"))) {
        throw "项目内置的 summarize-bilibili-video skill 不完整。"
    }
    $resolvedCodexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        Join-Path $env:USERPROFILE ".codex"
    } else {
        $env:CODEX_HOME
    }
    $installedSkillDir = Join-Path $resolvedCodexHome "skills\summarize-bilibili-video"
    $installedAgentsDir = Join-Path $installedSkillDir "agents"
    New-Item -ItemType Directory -Path $installedAgentsDir -Force | Out-Null
    $skillFiles = @(
        @((Join-Path $bundledSkillDir "SKILL.md"), (Join-Path $installedSkillDir "SKILL.md")),
        @((Join-Path $bundledSkillDir "agents\openai.yaml"), (Join-Path $installedAgentsDir "openai.yaml"))
    )
    $updated = $false
    foreach ($pair in $skillFiles) {
        $sourceFile = $pair[0]
        $targetFile = $pair[1]
        if (-not (Test-Path -LiteralPath $sourceFile)) { throw "项目内置 skill 缺少文件：$sourceFile" }
        $needsCopy = -not (Test-Path -LiteralPath $targetFile)
        if (-not $needsCopy) {
            $needsCopy = (Get-FileHash -Algorithm SHA256 $sourceFile).Hash -ne (Get-FileHash -Algorithm SHA256 $targetFile).Hash
        }
        if ($needsCopy) {
            Copy-Item -LiteralPath $sourceFile -Destination $targetFile -Force
            $updated = $true
        }
    }
    if ($updated) { Write-Host "[Skill] 已同步项目内置总结规则。" -ForegroundColor Cyan }
}

function Find-BilibiliUrl {
    param([AllowEmptyString()][string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $pattern = 'https?://(?:[\w-]+\.)?bilibili\.com/video/[^\s<>"）】》」]+|https?://(?:[\w-]+\.)?b23\.tv/[^\s<>"）】》」]+'
    $match = [regex]::Match($Text, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $match.Success) { return $null }
    $trailingPunctuation = [char[]]".,;!)]}，。；！？）》】」"
    return $match.Value.TrimEnd($trailingPunctuation)
}

try {
    if ($PSBoundParameters.ContainsKey("TestUrlInput")) {
        $testUrl = Find-BilibiliUrl $TestUrlInput
        if (-not $testUrl) { throw "没有从输入文字中找到 B 站单视频链接。" }
        Write-Output $testUrl
        exit 0
    }

    $cacheDir = Join-Path $projectRoot ".cache"
    $hfHome = Join-Path $cacheDir "huggingface"
    $pipCache = Join-Path $cacheDir "pip"
    $runtimeTemp = Join-Path $stateDir "temp"
    New-Item -ItemType Directory -Path $hfHome, $pipCache, $runtimeTemp -Force | Out-Null
    $env:HF_HOME = $hfHome
    $env:PIP_CACHE_DIR = $pipCache
    $env:TEMP = $runtimeTemp
    $env:TMP = $runtimeTemp
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    $localCpuModel = Join-Path $cacheDir "models\faster-whisper-small"
    if ((Test-Path (Join-Path $localCpuModel "model.bin")) -and (Test-Path (Join-Path $localCpuModel "config.json"))) {
        if (-not $env:BILI_NOTES_CPU_MODEL) { $env:BILI_NOTES_CPU_MODEL = $localCpuModel }
        if (-not $env:BILI_NOTES_GPU_MODEL) { $env:BILI_NOTES_GPU_MODEL = $localCpuModel }
    }

    Require-Command "python" "没有找到 Python。请安装 Python 3.11 或更新版本。"
    Require-Command "ffmpeg" "没有找到 FFmpeg。请先安装 FFmpeg 并加入 PATH。"
    Require-Command "ffprobe" "没有找到 FFprobe。请确认 FFmpeg 安装完整。"
    Require-Command "codex.cmd" "没有找到 Codex CLI。请先安装并登录 Codex。"
    Sync-BundledSkill

    if (-not (Test-Path $venvPython)) {
        Write-Host "[首次设置] 创建项目独立 Python 环境……" -ForegroundColor Cyan
        & python -m venv (Join-Path $projectRoot ".venv")
        if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败。" }
    }

    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $requirementsHash = (Get-FileHash -Algorithm SHA256 $requirements).Hash
    $stampPath = Join-Path $stateDir "requirements.sha256"
    $installedHash = if (Test-Path $stampPath) { (Get-Content -Raw -Encoding UTF8 $stampPath).Trim() } else { "" }
    $importsOk = $false
    if ($installedHash -eq $requirementsHash) {
        & $venvPython -c "import bleach, faster_whisper, markdown, yt_dlp" 2>$null
        $importsOk = $LASTEXITCODE -eq 0
    }

    if (-not $importsOk) {
        Write-Host "[首次设置] 安装下载、转写和阅读页依赖……" -ForegroundColor Cyan
        & $venvPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。请检查网络和上方 pip 输出。" }
        [System.IO.File]::WriteAllText($stampPath, $requirementsHash, $utf8)
    }

    Add-ProjectGpuRuntimeToPath

    if ($SetupOnly) {
        Write-Host "环境准备完成。" -ForegroundColor Green
        exit 0
    }

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $clipboardText = ""
    try { $clipboardText = Get-Clipboard -Raw -ErrorAction Stop } catch { }
    $initialUrl = Find-BilibiliUrl $clipboardText
    if (-not $initialUrl) { $initialUrl = "" }

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "B站视频总结"
    $form.StartPosition = "CenterScreen"
    $form.ClientSize = New-Object System.Drawing.Size(610, 390)
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "复制链接，选择你想读到多深"
    $title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 18, [System.Drawing.FontStyle]::Bold)
    $title.AutoSize = $true
    $title.Location = New-Object System.Drawing.Point(28, 24)
    $form.Controls.Add($title)

    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "单集或整套合集的原视频、转写、画面和总结会长期保存在本地。"
    $hint.ForeColor = [System.Drawing.Color]::FromArgb(90, 100, 94)
    $hint.AutoSize = $true
    $hint.Location = New-Object System.Drawing.Point(31, 65)
    $form.Controls.Add($hint)

    $urlLabel = New-Object System.Windows.Forms.Label
    $urlLabel.Text = "B 站分享文字、视频或合集链接"
    $urlLabel.AutoSize = $true
    $urlLabel.Location = New-Object System.Drawing.Point(30, 102)
    $form.Controls.Add($urlLabel)

    $urlBox = New-Object System.Windows.Forms.TextBox
    $urlBox.Location = New-Object System.Drawing.Point(32, 128)
    $urlBox.Size = New-Object System.Drawing.Size(546, 28)
    $urlBox.Text = $initialUrl
    $form.Controls.Add($urlBox)

    $collectionPanel = New-Object System.Windows.Forms.Panel
    $collectionPanel.Location = New-Object System.Drawing.Point(32, 170)
    $collectionPanel.Size = New-Object System.Drawing.Size(546, 252)
    $collectionPanel.BackColor = [System.Drawing.Color]::FromArgb(246, 244, 238)
    $collectionPanel.Visible = $false
    $form.Controls.Add($collectionPanel)

    $collectionTitle = New-Object System.Windows.Forms.Label
    $collectionTitle.Text = "检测到多集视频"
    $collectionTitle.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 12, [System.Drawing.FontStyle]::Bold)
    $collectionTitle.AutoSize = $false
    $collectionTitle.AutoEllipsis = $true
    $collectionTitle.Size = New-Object System.Drawing.Size(518, 26)
    $collectionTitle.Location = New-Object System.Drawing.Point(12, 10)
    $collectionPanel.Controls.Add($collectionTitle)

    $collectionMeta = New-Object System.Windows.Forms.Label
    $collectionMeta.AutoSize = $true
    $collectionMeta.ForeColor = [System.Drawing.Color]::FromArgb(82, 101, 91)
    $collectionMeta.Location = New-Object System.Drawing.Point(14, 40)
    $collectionPanel.Controls.Add($collectionMeta)

    $collectionList = New-Object System.Windows.Forms.ListView
    $collectionList.Location = New-Object System.Drawing.Point(14, 66)
    $collectionList.Size = New-Object System.Drawing.Size(518, 126)
    $collectionList.View = [System.Windows.Forms.View]::Details
    $collectionList.HeaderStyle = [System.Windows.Forms.ColumnHeaderStyle]::None
    $collectionList.FullRowSelect = $true
    $collectionList.MultiSelect = $false
    $collectionList.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    $collectionList.BackColor = [System.Drawing.Color]::FromArgb(255, 253, 248)
    [void]$collectionList.Columns.Add("集", 48)
    [void]$collectionList.Columns.Add("标题", 398)
    [void]$collectionList.Columns.Add("时长", 66)
    $collectionPanel.Controls.Add($collectionList)

    $wholeCollection = New-Object System.Windows.Forms.RadioButton
    $wholeCollection.Text = "整套处理为一个学习项目（推荐）"
    $wholeCollection.Location = New-Object System.Drawing.Point(16, 200)
    $wholeCollection.AutoSize = $true
    $wholeCollection.Checked = $true
    $collectionPanel.Controls.Add($wholeCollection)

    $currentPartOnly = New-Object System.Windows.Forms.RadioButton
    $currentPartOnly.Text = "只处理当前这一集"
    $currentPartOnly.Location = New-Object System.Drawing.Point(286, 200)
    $currentPartOnly.AutoSize = $true
    $collectionPanel.Controls.Add($currentPartOnly)

    $strengthLabel = New-Object System.Windows.Forms.Label
    $strengthLabel.Text = "总结强度"
    $strengthLabel.AutoSize = $true
    $strengthLabel.Location = New-Object System.Drawing.Point(30, 178)
    $form.Controls.Add($strengthLabel)

    $quick = New-Object System.Windows.Forms.RadioButton
    $quick.Text = "快览  ·  5分钟掌握核心"
    $quick.Location = New-Object System.Drawing.Point(34, 208)
    $quick.AutoSize = $true
    $form.Controls.Add($quick)

    $standard = New-Object System.Windows.Forms.RadioButton
    $standard.Text = "标准  ·  推理主线、案例、边界与复习清单（推荐）"
    $standard.Location = New-Object System.Drawing.Point(34, 240)
    $standard.AutoSize = $true
    $standard.Checked = $true
    $form.Controls.Add($standard)

    $deep = New-Object System.Windows.Forms.RadioButton
    $deep.Text = "深度  ·  可脱离视频阅读的完整学习稿"
    $deep.Location = New-Object System.Drawing.Point(34, 272)
    $deep.AutoSize = $true
    $form.Controls.Add($deep)

    $startButton = New-Object System.Windows.Forms.Button
    $startButton.Text = "开始总结"
    $startButton.Location = New-Object System.Drawing.Point(420, 326)
    $startButton.Size = New-Object System.Drawing.Size(158, 40)
    $startButton.BackColor = [System.Drawing.Color]::FromArgb(22, 139, 98)
    $startButton.ForeColor = [System.Drawing.Color]::White
    $startButton.FlatStyle = "Flat"
    $form.Controls.Add($startButton)
    $form.AcceptButton = $startButton

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "取消"
    $cancelButton.Location = New-Object System.Drawing.Point(322, 326)
    $cancelButton.Size = New-Object System.Drawing.Size(86, 40)
    $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancelButton)
    $form.CancelButton = $cancelButton

    $env:PYTHONPATH = Join-Path $projectRoot "src"
    $script:selectedUrl = $null
    $script:selectedStrength = "standard"
    $script:selectedCollection = $false
    $script:probedUrl = $null
    $script:probeData = $null
    $wholeCollection.Add_CheckedChanged({
        if ($wholeCollection.Checked -and $script:probeData -and $script:probeData.kind -eq "collection") {
            $startButton.Text = "处理整套 $($script:probeData.part_count) 集"
        }
    })
    $currentPartOnly.Add_CheckedChanged({
        if ($currentPartOnly.Checked) { $startButton.Text = "只处理当前这一集" }
    })
    $startButton.Add_Click({
        $value = Find-BilibiliUrl $urlBox.Text
        if (-not $value) {
            [System.Windows.Forms.MessageBox]::Show("请粘贴 B 站分享文字、视频或合集链接。", "链接有误", "OK", "Warning") | Out-Null
            return
        }
        $urlBox.Text = $value

        if ($script:probedUrl -ne $value) {
            $startButton.Enabled = $false
            $startButton.Text = "正在识别选集……"
            $urlBox.Enabled = $false
            $form.UseWaitCursor = $true
            [System.Windows.Forms.Application]::DoEvents()
            [System.IO.File]::WriteAllText($probeResultFile, "{}", $utf8)
            & $venvPython -m bili_notes --url $value --probe-only --result-file $probeResultFile
            $probeExitCode = $LASTEXITCODE
            $probe = $null
            if (Test-Path $probeResultFile) {
                try { $probe = Get-Content -Raw -Encoding UTF8 $probeResultFile | ConvertFrom-Json } catch { }
            }
            $form.UseWaitCursor = $false
            $urlBox.Enabled = $true
            $startButton.Enabled = $true
            $startButton.Text = "开始总结"
            if ($probeExitCode -ne 0 -or -not $probe -or -not $probe.ok) {
                $probeError = if ($probe -and $probe.error) { [string]$probe.error } else { "无法识别这个链接，请查看控制台输出。" }
                [System.Windows.Forms.MessageBox]::Show($probeError, "识别失败", "OK", "Error") | Out-Null
                return
            }
            $script:probedUrl = $value
            $script:probeData = $probe

            if ($probe.kind -eq "collection") {
                $collectionList.Items.Clear()
                foreach ($part in $probe.parts) {
                    $row = New-Object System.Windows.Forms.ListViewItem(("P{0:d2}" -f [int]$part.index))
                    $partText = if ($part.display_title) { [string]$part.display_title } else { [string]$part.title }
                    [void]$row.SubItems.Add($partText)
                    [void]$row.SubItems.Add([string]$part.duration_display)
                    [void]$collectionList.Items.Add($row)
                }
                $collectionTitle.Text = [string]$probe.title
                $collectionMeta.Text = "检测到 $($probe.part_count) 集 · 总时长 $($probe.total_duration_display) · 将共用一份总学习页"
                $currentPartOnly.Text = "只处理当前第 $($probe.current_part) 集"
                $collectionPanel.Visible = $true
                $form.ClientSize = New-Object System.Drawing.Size(610, 650)
                $strengthLabel.Location = New-Object System.Drawing.Point(30, 438)
                $quick.Location = New-Object System.Drawing.Point(34, 468)
                $standard.Location = New-Object System.Drawing.Point(34, 500)
                $deep.Location = New-Object System.Drawing.Point(34, 532)
                $cancelButton.Location = New-Object System.Drawing.Point(322, 590)
                $startButton.Location = New-Object System.Drawing.Point(420, 590)
                $startButton.Text = "处理整套 $($probe.part_count) 集"
                return
            }
        }

        $script:selectedUrl = $value
        $script:selectedCollection = $script:probeData -and $script:probeData.kind -eq "collection" -and $wholeCollection.Checked
        if ($quick.Checked) { $script:selectedStrength = "quick" }
        elseif ($deep.Checked) { $script:selectedStrength = "deep" }
        else { $script:selectedStrength = "standard" }
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    })

    $dialogResult = $form.ShowDialog()
    if ($dialogResult -ne [System.Windows.Forms.DialogResult]::OK -or -not $script:selectedUrl) {
        exit 0
    }

    [System.IO.File]::WriteAllText($resultFile, "{}", $utf8)
    Set-Location $projectRoot
    Write-Host "`n任务已开始。窗口会显示下载、转写和总结进度。`n" -ForegroundColor Cyan
    $workflowArgs = @("-m", "bili_notes", "--url", $script:selectedUrl, "--strength", $script:selectedStrength, "--result-file", $resultFile)
    if ($script:selectedCollection) { $workflowArgs += "--collection" }
    & $venvPython @workflowArgs
    $workflowExitCode = $LASTEXITCODE

    $result = $null
    if (Test-Path $resultFile) {
        try { $result = Get-Content -Raw -Encoding UTF8 $resultFile | ConvertFrom-Json } catch { }
    }
    if ($workflowExitCode -eq 0 -and $result -and $result.ok) {
        Start-Process -FilePath $result.html
        [System.Windows.Forms.MessageBox]::Show("总结完成，离线学习页已经打开。", "完成", "OK", "Information") | Out-Null
        exit 0
    }

    $errorText = if ($result -and $result.error) {
        [string]$result.error
    } else {
        "处理进程异常退出（代码 $workflowExitCode）。请把控制台最后几行发给 Codex；视频与已完成步骤会保留并在下次复用。"
    }
    Write-Host ("处理失败：" + $errorText) -ForegroundColor Red
    [System.Windows.Forms.MessageBox]::Show($errorText, "处理失败", "OK", "Error") | Out-Null
    if ($workflowExitCode -eq 0) { $workflowExitCode = 1 }
    exit $workflowExitCode
}
catch {
    Write-Host ("启动失败：" + $_.Exception.Message) -ForegroundColor Red
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "启动失败", "OK", "Error") | Out-Null
    } catch {
        Write-Error $_.Exception.Message
    }
    exit 1
}
