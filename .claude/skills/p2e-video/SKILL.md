---
name: p2e-video
description: 帮 Paper2Experiment（EE6008 第 28 组）的组员做课程视频：小组 5 分钟视频里自己负责的片段，和约 3 分钟的个人视频。先问名字、确定他负责哪部分，给出按时长写好的英文旁白，等他发来录音（mp3/m4a），再生成 1080p 画面、对齐的字幕、降噪并统一音量的 mp4。macOS、Windows、Linux 都能用。组员说"做视频""小组视频""个人视频""录旁白""p2e-video"，或者发来旁白录音时使用。
---

# p2e-video：小组片段 + 个人视频

整个流程是组长的四个片段和个人视频实际用过的做法，已经固化成一个工具 `scripts/p2e_video.py`。你的工作是：
问清是谁 → 给稿子 → 等录音 → 按录音做画面 → 用工具出片 → 检查 → 交付。
规范见 `reference/style.md`，每个人的稿子见 `reference/members.md`。

跟组员说话用中文；旁白和视频里的文字用英文。

**路径约定**：下文 `SKILL` 指本 skill 的目录（仓库里的 `.claude/skills/p2e-video`），`WORK` 指这个组员的工作目录
`docs/presentation/<拼音名小写>/`（如 `docs/presentation/wangyiming/`）。写命令时换成真实路径；
Windows 上路径用正斜杠或加引号都可以，含空格的路径一定加引号。所有命令在仓库根目录运行。

## 第 1 步 · 问名字，确定部分

问："你叫什么名字？"按 `reference/members.md` 的表对上部分，然后用一张小表告诉他：负责的部分、小组片段号、
在全片里的时间、**时长上限**，以及个人视频约 3 分钟。组长 HU YANZHI 的片段和个人视频已经做完。

## 第 2 步 · 给稿子和录音要求

把 `members.md` 里他的**小组片段旁白**和**个人视频旁白**原样给他（个人视频按节列出）。同时说清：

1. 小组片段和个人视频**分两个文件**录；个人视频可以一次录完，各节之间停 1–2 秒。
2. 安静房间、耳机麦克风；句与句之间停半秒到一秒（画面在停顿处切换）。
3. sha256 念 "sha two five six"，0.25 念 "zero point two five"，7.6 念 "seven point six"。
4. 录好后把文件路径发过来（mp3、m4a、wav 都行）。

然后等录音。等的时候做第 3 步。

## 第 3 步 · 准备环境（只需一次）

唯一要先装的是 **uv**（它会自动装好 Python 和其余依赖）：

| 系统 | 安装 uv |
|---|---|
| macOS / Linux | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Windows（PowerShell） | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`，或 `winget install astral-sh.uv` |

装完**重新打开终端**，然后：

```bash
uv run SKILL/scripts/p2e_video.py setup
```

它会装 Playwright 的无头 Chromium、下载语音识别模型（faster-whisper base.en，约 150 MB），并检查 ffmpeg。
系统里没有 ffmpeg 也没关系：工具会用 imageio-ffmpeg 自带的那一份。之后所有命令都是 `uv run SKILL/scripts/p2e_video.py <命令>`。

**需要 demo 网站画面的部分**（2、3、6 的小组片段，以及 2、3、6 的个人视频）：

- 网址 `https://paper2experiment.allenhu.com`，门口要填名字和**访问码**。访问码不写在这里（仓库是公开的），
  请组员向组长 HU YANZHI 要，并**由组员自己在浏览器里输入**，不要替他输；输过一次网站会记住。
- 示例任务统一选 **capsule-6460826（CULP）**，模型 Claude Haiku 5.5；A、B、D 用同一个任务。
- 录法：组员自己全屏录一次完整运行（从选任务到出结果表），macOS 用 QuickTime / ⌘⇧5，Windows 用 Win+Alt+R
  （Xbox Game Bar）或 Win+Shift+S 的录屏，把视频发给你；你用 `frames` 拆成帧，按 `templates/example-demo-frames.html`
  的做法（快放 → 停在完整的图上加蓝框标签 → 切到结果表）做页面。
- 一次运行只花几美分，每人跑一两次够用。

## 第 4 步 · 收到录音：取时刻、写字幕、查时长

```bash
uv run SKILL/scripts/p2e_video.py transcribe "录音.mp3" WORK/rec01
```

打印每个词的开始时刻（存为 `words.csv`）和停顿表（`pauses.txt`，"a-b" 里 b 是下一句开口的时刻）。然后：

1. **核对内容**：对照稿子看有没有漏句、错句。漏了关键句就请他补录；只是多个 "the" 之类不用重录。
2. **查时长**：小组片段超过上限，就请他念快一点重录，或删掉稿子里标了 *(可删)* 的句子再录。
3. **写 SRT**（UTF-8）：每句一条，起止时刻取停顿，文字用稿子原文（规则见 `style.md` 的"字幕"）。
4. 个人视频录在一个文件里时，按节之间的长停顿（≥ 1 s）分节，记下每节的起止时刻。

## 第 5 步 · 做画面

把 `SKILL/templates/engine.js`、`base.css` 复制到 WORK，再把 `slide-template.html` 复制成 `WORK/clip.html`。
按 `members.md` 里"画面"一列写场景：一组句子一个 `<section class="scene" data-start=…>`，元素的 `data-t` 对到词。
两个成品可以照着改：

- `templates/example-slides.html`：纯图文（组长的 06：大字、卡片、终端打字效果、高亮）
- `templates/example-demo-frames.html`：demo 截图（组长的 04：快放、放大、蓝框标签、切结果表）；
  它引用的 `fr/` 帧不在 skill 里，换成你用 `frames` 拆出的帧

现成素材在 `SKILL/assets/`：`01-architecture.en.png`（架构图）、`02-planner-runtime.en.png`（D 的 Planner + Runtime）、
`03-skills-loop.en.png`（skill 循环）、`04-workflows.en.png`（三个工作流对比）、`changelog.png`（demo 网站 Changelog
长截图，2200 px 宽）。报告数字在 `Base/runs/reports/`。**数字只用报告和代码里有的**，`members.md` 每段后面列了出处。

先抽单帧看，不用等全片：

```bash
uv run SKILL/scripts/p2e_video.py render WORK/clip.html WORK/still.mp4 --start 12.5 --dur 0.04 --srt WORK/clip.srt
uv run SKILL/scripts/p2e_video.py sheet WORK/still.mp4 WORK/still.png 0
```

然后打开 `still.png` 看：元素在对应的词出现、字幕不挡内容、字够大、截图里的字看得清。

## 第 6 步 · 出片

```bash
uv run SKILL/scripts/p2e_video.py build WORK/clip.html "录音.mp3" WORK/clip.srt WORK/out 07_experiments_WangYiming 38.5
```

参数依次是：页面、录音、字幕、输出目录、文件名、总时长（= 页面里的 `END`）。个人视频加 `--target -14.4`。
它会降噪并逐句统一音量、渲染两遍（有字幕和无字幕）、合成，最后打印时长、响度和峰值。

## 第 7 步 · 检查和交付

```bash
uv run SKILL/scripts/p2e_video.py sheet WORK/out/07_experiments_WangYiming_subtitled.mp4 WORK/sheet.png 2 9 16 24 31 37
```

在几个关键词的时刻抽帧看一遍；确认时长不超、响度是 -16（个人 -14.4）LUFS、句间差 ≤ 1 LU（`build` 会打印）。
把三个文件（无字幕 mp4、带字幕 mp4、srt）的路径告诉组员，请他把小组片段发给组长 HU YANZHI 拼接，个人视频自己提交。
提醒他完整看一遍、听一遍。

## 组长拼接全片（只有组长需要）

```bash
uv run SKILL/scripts/p2e_video.py merge 小组视频.mp4 01.mp4 02.mp4 03.mp4 04.mp4 05.mp4 06.mp4 07.mp4 08.mp4
```

用无字幕版拼；要字幕就直接拼带字幕版。全片不能超过 5:00（命令会打印总长）。

## 常见问题

| 现象 | 处理 |
|---|---|
| `uv` 找不到 | 装完 uv 后要重新打开终端；Windows 上也可以 `py -m pip install uv` |
| `setup` 说 ffmpeg 缺功能 | 装完整版 ffmpeg：macOS `brew install ffmpeg`，Windows `winget install Gyan.FFmpeg`，然后重开终端 |
| 下载模型很慢或失败 | 网络问题；重跑 `setup` 会接着下载 |
| 中文或空格路径报错 | 路径加引号；仍报错就把录音复制到 WORK 下、改成英文文件名 |
| 渲染出来字体不一样 | 正常：macOS 用系统字体，Windows 用 Segoe UI / Arial，排版一致 |
