# CORE-Bench 盘点：主实验的数据怎么划分

日期：2026-10-17。数据来源于任务元数据和各 capsule 下载链接的 HTTP 头（Content-Length）。盘点时没有下载任何 capsule。逐个 capsule 的明细见 `Base/benchmark/corebench_capsule_sizes.tsv`。

## 1. 两个划分

| 划分 | 来源 | 题数 | 用途 |
|---|---|---|---|
| dev | 原版 CORE-Bench 的 train 集（`core_train.json`，从 GitHub siegelz/core-bench 获取，sha256 `3df47f1b…`） | 45 | 调优工作流、升级 skill 库，可以反复跑 |
| test | CORE-Bench v1.1 mainline（`core_test.json`，Hugging Face agent-evals） | 39 | 代码和 skill 库都冻结之后只跑一次 |

两个集合没有重叠（按 capsule_id 核对过）。v1.1 mainline 也没有自带 train 集，所以开发集只能取原版的 train 集。这样做也有好处：调优数据和测试数据都由 CORE-Bench 官方划分，不是我们自己挑的。

**试跑过的 5 个 capsule 要排除出测试集。** 2026-10-16 搭适配器时，我们在 v1.1 的 5 个 capsule（0201673、6049678、7655932、7800694、8412128）上试跑了三轮，并且根据结果修过评分器。这 5 题在开发阶段已经看过，不能再算测试题。代码里 `corebench.PILOTED` 记录了这份名单，导出测试集时自动跳过，命令行也拒绝在测试集上跑这 5 题。

## 2. 按语言和题型分

每个 capsule 都看两项：用什么语言，有没有要看图才能回答的问题（问题文本里含 "fig"）。

| | dev（45） | test（去掉试跑后 34，其中 CPU 30） |
|---|---|---|
| 需要 GPU | 0（train 集没有 GPU 字段，按 CPU 计，开跑时再确认） | 4 |
| Python，不看图 | 20 题，3.4 GB | **2 题**，3.2 GB |
| Python，要看图 | 7 题，0.3 GB | 7 题，0.4 GB |
| R，不看图 | 3 题 | 3 题 |
| R，要看图 | 15 题 | 18 题 |
| 合计（CPU） | 45 题，5.8 GB | 30 题，4.6 GB |

这张表决定了主实验能不能成立：

- **只跑"Python + 不看图"，测试集只剩 2 题**，撑不起主结论。
- **加上读图能力**（给 agent 一个看图工具，haiku55 本身能处理图片），Python 测试题变成 9 题。
- **再加上 R 环境**，测试题变成 30 题，开发题 45 题。本机现在没有装 R。

所以想让 CORE-Bench 当主实验，读图和 R 两项都需要支持。

## 3. 磁盘和下载

- 本机剩余空间约 15 GB（占用 93%）。dev 和 test 全部 capsule 加起来约 11.6 GB，不能一次全下完。
- 超过 1 GB 的 capsule：dev 有 0220918（1.9 GB）和 0325493（1.1 GB）；test 有 3762736（2.2 GB）和 2242462（1.1 GB）。
- 做法：分批下载 → 运行 → 删除工作区（现在已经默认删除）。压缩包留着，方便重跑；磁盘吃紧时可以先删大压缩包。

## 4. 成本和时间（估计）

试跑的 5 个小 capsule 平均每次运行花费：A $0.004、D $0.008，耗时 1–6 分钟。开发集的 capsule 更大，v4 论文的单次运行花费是 $0.03–0.08，最长 3.4 小时。按每次运行 $0.01–0.10、10–30 分钟估算，一轮"20 题 × 3 组"共 60 次运行，花费约 $1–6，串行跑需要 10–30 小时。时间比钱更紧张。

## 5. 已实现的部分（离线测试通过）

| 内容 | 位置 |
|---|---|
| dev / test 两个划分的路径、来源、下载地址；运行时记录 `split` | `p2e/corebench.py`（`split_of`、`split_paths`、`CAPSULE_URL`、`PILOTED`） |
| `p2e corebench export --split dev|test [--languages Python R] [--vision]` | `p2e/cli.py` |
| `p2e corebench download --split dev [capsule...]` | 同上 |
| 在测试集上运行时：拒绝试跑过的 capsule、要求 skill 库已冻结、不允许升级 skill | 同上 |
| `--update-skills`：一批开发集运行结束后做一轮 skill 升级 | 同上，`p2e/skills.py` |
| 已导出：dev 集中"Python + 不看图"的 20 题 | `Base/benchmark/corebench_v1_train/tasks/` |

## 6. 已决定（2026-10-17）

| 事项 | 做法 |
|---|---|
| R 环境 | micromamba 装在 `~/.p2e-mamba`，不动系统。agent 用 `micromamba create -p ./.renv ...` 在工作区里建 R 环境，运行结束随工作区一起删除；包缓存共用，建一个环境约 8 秒 |
| 看图工具 | 所有 agent 都拿到同一个 `view_image` 工具：用 macOS 自带的 `sips` 转成 PNG，最长边缩到 1568 像素；Anthropic 模型直接收到图片；trace 里只记字节数，不存图片内容 |
| skill 库 | v2：v1 的 6 个 skill，加上 r-environment |
| 第一批下载 | dev 集里 Python、不看图的 20 题（3.4 GB）。官方服务器限制单条连接的速度，改成 8 条并行下载，可断点续传 |
| 磁盘 | 每次运行结束删除工作区；每轮结束修剪 uv 缓存 |

## 7. 第一轮之后的调整（2026-10-18）

| 事项 | 做法 |
|---|---|
| Hard 级清理 | 改成按 CORE-Bench 原论文的定义：只删结果目录、复现说明、环境配置（environment/）和运行脚本，数据和 checkpoint 全部保留；`__pycache__` 仍然删掉。HAL harness 还会删训练数据、缓存和 checkpoint，第一轮里有 2 道题因此没法做（题目要求评估一个被删掉的 checkpoint，或者读一个被删掉的训练文件）。捷径风险仍由"数值必须来自本次运行"的检查来防 |
| 不计分的题 | 一道题的所有问题都因为噪声太大（h 超过均值的 5%）而不计分时，判为 unscored，不计入通过率；原来被误判为 fail |
| 第二轮 | dev 集全部 45 题（Python 27、R 18，含看图题），skill 库 v4 |
| 磁盘 | 每题的三组都跑完后清空 uv 和 micromamba 的缓存；每次运行前检查剩余空间（不到 6 GB 先清缓存，还不到 4 GB 就停止） |

## 8. 第二轮（2026-10-18 至 10-19）

dev 集 45 题 × A、B、D，共 135 次，skill 库 v4。完整报告：`Base/runs/reports/cb_dev_round2.md`。

| 事项 | 做法 |
|---|---|
| 防泄漏检查的误报 | 题目标识如果本身是普通英文单词（以 `/usr/share/dict/words` 为准，允许 -s、-es、-ed、-ing 词尾），就不再当作泄漏。整理器写的 "glmm fits" 因此被拦，整轮修订都没生效。修好后重新应用同一份整理结果，skill 库升到 v5 |
| 数值来源检查 | `./.renv`（micromamba 装的 R 环境）以前不在排除名单里，答案会在几千个环境文件里"找到"。已加入排除名单，从第三轮起生效；第二轮的工作区已删除，没法重新检查 |
| 已知问题 | 看图题里问坐标轴标签这类文字答案，标签本来就写在绘图代码里，而图是 PDF，搜不到文字，所以会被判为"只在原有文件里出现"（第二轮 A 组 8912293 有一题因此判错） |

## 9. 第三轮之前的改进（2026-10-27）

| 事项 | 做法 |
|---|---|
| 看图题的文字答案 | 检查答案来源时，会用 pypdf 抽出 PDF 里的文字一起搜。从生成的 PDF 图上读出来的坐标轴标签，算作本次运行产生的答案；`.pdf` 也不再算"无法检查的结果文件" |
| 不计分的题 | 报告里会单独列出它们按 HAL 口径的结果 |
| 依赖版本 | `Base/uv.lock` 锁定了版本，README 里写了按锁文件重建环境的命令；`Base/.env` 改成了真文件 |
| 断点续跑 | `corebench run --skip-done STAMP`：跳过 STAMP 之后已经跑完的运行，判断依据是题目、工作流、模型、第几次重复、skill 开还是关 |
| 并行 | `corebench run --jobs N`：同时跑 N 道题，每道题在单独的子进程里跑，用各自的 uv 缓存和 micromamba 包缓存（`P2E_UV_CACHE`、`P2E_MAMBA_PKGS`）。注意并行时 CPU 是共用的，所以耗时这一项的可比性会差一些 |
| 防睡眠 | 批量运行开始后，会在 macOS 上用 `caffeinate -i -w <pid>` 阻止系统空闲睡眠，直到批次结束 |
| 关闭 skill 的对照组 | 设置 `P2E_SKILLS=off` 跑出来的运行，目录名后面会多一个 `_noskills` |
| 指定题号下载 | `corebench download --split dev capsule-…` 现在接受写在选项后面的题号 |

第三轮（`Base/runs/round3.sh`，起始时间戳 20261027-1050，2 个任务并行，skill 库 v5，中途不升级 skill）：
- 第 1 部分：Haiku55 和 Sonnet55，skill 开启，45 题 × A、B、D，共 270 次；
- 第 2 部分：Haiku55，skill 关闭，45 题 × A、B、D，共 135 次。

## 10. 第三轮（2026-10-27 至 11-01）和看图题评分的修正

第三轮 405 次全部完成。中途被打断三次（10/28 凌晨内存不足导致系统卡死，同日下午系统更新后重启，10/31 swap 占满磁盘），被打断的运行都整次重跑，已完成的结果全部保留。详细结果见 `Base/runs/reports/cb_dev_round3_summary.md`，主要结论：

| 问题 | 结论 |
|---|---|
| 三个工作流 | 开 skill 时 D 最好（Haiku：A 32、B 33、D 35 / 42），但差距不显著；不开 skill 时三者打平 |
| Sonnet55 vs Haiku55 | 通过率相同（各 100/126），Sonnet 花费是 7.6 倍；主实验继续用 Haiku55 |
| skill 开 vs 关 | 100 vs 95，只对 D 有帮助（35 vs 31），p = 0.36 |
| v5 vs v4 | 都是 100/126，没有可测量的差别 |

**看图题评分规则（11/01 修改）**：看图题的正确答案，如果在任何文本里都找不到，但这次运行用 `view_image` 查看过一张本次运行生成的图片（开跑前的快照里没有，或者内容变了），就算本次运行产出。之前 PNG 图上读出的答案只能判为"找不到"，A、B 每组因此少算 2–3 道题。第二轮这些题能通过，靠的是 `.renv` 文件里的误报。评分器和 D 的完成检查用同一条规则。所有旧运行都用快照和 trace 离线重算过（`corebench.rescore_viewed_figures`，原文件保存为 `*.pre-figures.json`）：第三轮 14 次从 partial 改为 full，第一、二轮不变。

报告工具新增 `--profile` 和 `--skills on|off` 参数，混合了模型或 skill 开关的批次可以分组出报告。
