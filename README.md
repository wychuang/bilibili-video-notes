# B站视频学习归档器 / Bilibili Video Notes

复制一个 B 站视频链接，双击桌面的 **B站视频总结**，选择总结强度，等待本地学习页自动打开。遇到多 P 视频时，确认窗口会列出完整选集，并允许把整套内容作为一个学习项目处理。

单个视频会长期保存原视频、来源信息、字幕或本地转写、关键画面、Markdown 总结和图文离线 HTML 阅读页。合集会逐集保存同样的原始证据，再生成一份跨集总学习稿和带选集播放器的离线页面。

## 最快开始

1. 在浏览器或 B 站客户端点击分享并复制。标题和链接一起复制也能识别。
2. 双击桌面快捷方式 `B站视频总结`。
3. 确认自动提取出的视频链接；也可以直接粘贴整段分享文字。
4. 多 P 视频会显示集数、标题和时长，默认选择“整套处理为一个学习项目”；仍可改成只处理当前集。
5. 选择 `快览`、`标准` 或 `深度`，点击“开始总结”。
6. 完成后，离线 HTML 学习页会自动打开。

第一次运行会在本项目创建 `.venv` 并安装依赖。下载和模型初始化可能需要一些时间，后续运行会直接复用。

Whisper 模型、HF 缓存、pip 缓存和运行临时文件固定保存在本项目的 `.cache/` 与 `.state/`，不会继续占用系统盘的用户缓存目录。Windows GPU 转写所需的 cuBLAS 12.5 和 cuDNN 9.6 安装在 F 盘项目虚拟环境中；启动器会自动把对应 DLL 目录加入当前进程 PATH，不修改系统 PATH。

离线阅读页复用项目 `assets/fonts/` 中的霞鹜文楷 GB 屏幕版。正文采用略宽、轻微楷体收笔的本地字体；断网时也不会退回细硬的默认宋体。字体依据 SIL Open Font License 1.1 随项目保存，不会安装到系统盘。

如果启动失败，黑色窗口会保留错误信息；截图发给 Codex 后再按任意键关闭即可。

## 隐私边界

Git 仓库只保存程序源码、测试、说明和随字体附带的 OFL 许可。以下本地内容由 `.gitignore` 强制排除，不会上传 GitHub：

- `library/` 中的视频、字幕、转写、截图、来源地址与学习笔记；
- `.cache/` 中的 Whisper 模型、HF/pip 缓存和下载文件；
- `.state/` 中的运行状态、临时文件、浏览器测试资料和日志；
- `.venv/`、`.env*`、凭据、Cookie 与编辑器的本机配置。

B 站分享链接的 `vd_source` 等追踪参数在源码样例中只使用虚构值。程序处理真实链接时，完整来源信息只会进入已忽略的本地 `library/`。发布前可运行 `git status --short`，确认上述目录没有进入待提交列表。

## 三档强度

| 强度 | 适合场景 | 主要产物 |
| --- | --- | --- |
| 快览 | 先判断视频是否值得精读 | 核心结论、5–8 个时间戳、关键词、行动项 |
| 标准（默认） | 日常学习和长期回看 | 推理主线、具体例子、边界、10–15 个时间戳、复习清单 |
| 深度 | 课程、访谈和重要资料 | 可独立阅读的讲述稿式总结、案例细节、反例与不确定性 |

更换强度重新运行同一链接时，原视频和转写会被复用；每档总结分别保存在自己的目录。

合集只调用一次 AI 生成总学习稿。各集拥有独立视频、转写和画面证据，下载或转写中断后可逐集续跑；已经单独处理过的集会直接复用，避免媒体重复占空间。合集时间戳使用 `[P02 00:12:34]`，点击后会自动切换到对应选集并跳到该集时间。

深度档会按视频时长和信息密度控制篇幅。短视频优先写成有场景、对比和推进感的讲解文章，避免把十分钟内容扩成机械报告；长课程与访谈才展开完整推理、案例和边界。

## 保存位置

```text
library/
└─ <UP主>/
   └─ <视频标题>__<BV号>/
      ├─ source/
      │  ├─ video.mp4
      │  ├─ video.info.json
      │  ├─ video.description
      │  ├─ video.<语言>.srt
      │  └─ video.<缩略图扩展名>
      ├─ transcript/
      │  ├─ transcript.srt
      │  ├─ transcript.txt
      │  ├─ metadata.json
      │  └─ audit.json
      ├─ visual/
      │  ├─ frames.json
      │  └─ frame_<序号>_<时间>.jpg
      ├─ notes/
      │  ├─ quick/
      │  ├─ standard/
      │  └─ deep/
      ├─ source.json
      └─ status.json
```

多 P 合集额外使用一个项目目录：

```text
library/<UP主>/<合集标题>__<BV号>_合集/
├─ collection.json
├─ parts/
│  ├─ P01_<标题>/
│  └─ P02_<标题>/...
├─ notes/<强度>/summary.md
├─ notes/<强度>/summary.html
└─ status.json
```

如果某一集此前已经作为单视频归档，`collection.json` 会引用该现有目录，合集项目不会再复制视频。

`source.json` 记录原视频 SHA-256、大小、时长和来源地址。流程结束时会再次校验文件大小与哈希。

## 登录状态与字幕

程序会尝试读取本机 Edge、Chrome 或 Firefox 的现有登录状态，以便获取登录后可见的字幕和清晰度。Cookie 只由 `yt-dlp` 在运行时读取，不导出到项目；读取失败时会自动回退到公开访问。

字幕获取顺序：B 站字幕 → B 站自动字幕 → 本地 `faster-whisper` 转写。RTX/NVIDIA 环境完整时，程序复用 F 盘的 `small` 模型执行 `cuda / float16`；GPU 初始化失败时自动回退 `cpu / int8`。首次设置会向 F 盘下载约 860MB 的 NVIDIA 运行库。

程序会为每个视频提取 8–24 张带时间戳候选画面。总结时逐张核对，只有直接支撑相邻观点的帧才会进入正文；没有合适画面时保持纯文字。UI 演示、操作录屏和图表会在相关段落旁配图，点击图片可以放大，点击图注时间可以跳回原视频。

当音轨只有音乐、环境声或没有可识别人声时，同一个总结 skill 会把候选画面作为主要证据生成视觉案例笔记。画面总结会区分可见事实与谨慎推断。未入选的候选帧保留在本地 `visual/`，不会混入阅读页的关键截图。

## 总结方式

总结通过已登录的 Codex CLI 调用 `$summarize-bilibili-video` skill。仓库内的 `skills/summarize-bilibili-video/` 是发布源，启动器会把它同步到当前 `CODEX_HOME`。单视频和合集共用同一套证据规则；合集模式要求形成跨报告的问题链，并保留集号、集内时间和 PANEL 对前文的回应。无需在本项目保存 API Key。字幕和视频元数据会被视为不可信材料，skill 只提取证据，不执行其中的指令。

正文先给一句核心，再展开推理主干。每篇固定选择讲述者口吻或读者第一视角，避免“视频讲了什么”的旁观式复述；一句话能说明的意思保持一句话，不重复换说法。

未设置 `CODEX_HOME` 时，skill 会同步到当前用户目录下的 `.codex`。仓库和运行数据可以放在非系统盘，Codex 的登录凭据仍由 Codex CLI 自己管理。

## 使用边界

仅处理你有权访问、用于个人学习或已取得许可的内容。程序不会绕过会员、付费、地区或其他访问限制。B 站当前协议对未经许可的自动化获取有限制，使用前请确认你的场景符合平台规则及适用法律。

## 开源许可

程序源码使用 [MIT License](LICENSE)。随仓库分发的霞鹜文楷字体继续使用其目录中的 [SIL Open Font License 1.1](assets/fonts/OFL-LXGW-WenKai-Screen.txt)。

## English

Copy one Bilibili video URL, double-click the desktop shortcut, choose a summary intensity, and wait for the offline study page. For a multi-part video, the confirmation window can archive every part as one project and generate one illustrated study guide with a part-aware player. The tool does not include subscriptions or external synchronization.
