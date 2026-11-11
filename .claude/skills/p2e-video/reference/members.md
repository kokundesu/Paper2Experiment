# 组员、分工和旁白

每个人做两样东西：**小组视频里的片段**（几十秒，拼进 5 分钟的小组视频）和**个人视频**（约 3 分钟，讲自己负责的部分）。
旁白全部是英文，按每秒约 1.9 个英文词估算时长（组长实测的语速）；录完按实际时长检查，超时就删标了 *(可删)* 的句子。

## 名字 → 部分

| 名字 | 部分 | 小组片段 | 个人视频 |
|---|---|---|---|
| HU YANZHI（组长） | 1 整体架构 + 工作流 D；4 可信评估 | 01、04、06、08（**已完成**） | 已完成 |
| LI ZHAOXIN | 2 Agent 设计 1：工作流 A | **02**（30 s） | 第 2 部分 |
| XU YUANHUI | 3 Agent 设计 2：工作流 B | **03**（25 s） | 第 3 部分 |
| JING KEYING | 5 任务和 skill 库 | **05**（40 s） | 第 5 部分 |
| WANG YIMING | 6 实验和展示 | **07**（40 s） | 第 6 部分 |

用户说的名字可能是拼音、中文或缩写（如 "WANGYIMING6"、"王一鸣"），按拼音对上表；对不上就让用户从表里选。

## 小组视频全片顺序（约 4:40）

| 片段 | 时间 | 内容 | 负责 | 状态 |
|---|---|---|---|---|
| 01 | 0:00–1:12 | 开头：问题、研究问题、架构 | HU | 已完成 |
| 02 | 1:12–1:42 | demo 怎么用 + 工作流 A | LI ZHAOXIN | 待做 |
| 03 | 1:42–2:07 | 工作流 B | XU YUANHUI | 待做 |
| 04 | 2:07–2:32 | 工作流 D | HU | 已完成 |
| 05 | 2:32–3:12 | 任务和 skill 库 | JING KEYING | 待做 |
| 06 | 3:12–3:37 | 可信评估 | HU | 已完成 |
| 07 | 3:37–4:17 | 实验和展示 | WANG YIMING | 待做 |
| 08 | 4:17–4:36 | 结论 | HU | 已完成 |

**demo 运行的示例任务统一用 CORE-Bench capsule-6460826（CULP: Classification Using Link Prediction）**：组长的
片段 04 和个人视频都用它（D 跑完 6/6 全对），A、B 也跑同一个，三个工作流的画面才能对比。它在 demo 服务器上跑得快。

---

# LI ZHAOXIN · 部分 2 · 工作流 A

## 小组片段 02（30 s）

**画面**：demo 网站首页 → 示例任务选 capsule-6460826 → 工作流选 A（single）、模型 Claude Haiku 5.5 → 发送 →
一张 agent 卡片，下面的工具调用在滚动（加速）→ 结果对照表。

> Let's see it live. In our demo, you can describe a task, or pick a CORE-Bench example. We pick one and run Workflow A, the single agent. One agent holds every tool in one conversation: it reads the task, installs the environment, runs the code and submits. It's simple and cheap, but nobody checks its work along the way.

（60 词，约 32 s。超时就删 "It's simple and cheap," 这半句。）

## 个人视频（约 2:45，308 词）

| 节 | 画面 | 旁白 |
|---|---|---|
| 开场 | 标题卡：名字、项目名、"Workflow A · single agent" | Hi, I'm Li Zhaoxin. In Paper2Experiment, I worked on Workflow A, the single-agent baseline that the other two designs are measured against. |
| 2.1 A 是什么 | `$K/assets/04-workflows.en.png` 左栏放大；工具列表 read · write · shell · view_image · read_skill 依次出现 | Workflow A is one ReAct agent with every tool: it can read and write files, run shell commands in the sandbox, view images, and read the skill library. In a single conversation, it reads the task, sets up the environment, runs the code, and submits its answers, each one citing the log that printed it. |
| 2.2 为什么要基线 | 三个工作流并排，A 标 "baseline"，B、D 标 "+ roles / + checks" | To know whether more structure helps, we need the simplest design first. A follows the style of agents used in benchmarks like PaperBench. Workflows B and D add roles and checks; A shows what an agent achieves without them. |
| 2.3 怎么实现 | `SingleAgent/workflow.py` 的 docstring 截图；三个框：turn limit · $5 budget · submission validated；最后一行红字 "no check during the run" | The harness runs each tool call inside the sandbox and records every message and every command log. The agent works within a turn limit and a five-dollar budget per run. Its submission is validated: values must come one per run, exactly as printed, and a malformed submission is sent back. But nothing checks the work during the run. Only the evaluator looks, at the very end. |
| 2.4 demo | demo 网站上 A 跑 capsule-6460826 的录屏（加速），最后停在结果对照表 | Here is A on our demo site. One agent card, and below it, every tool call as it happens: reading files, installing packages, running the code. At the end, its answers are compared with the paper. |
| 2.5 结果 | 结果表：A 29/30（$0.013/次）、B 28/30、D 26/30，A 行高亮；下方 "McNemar p ≥ 0.25 · not significant" | The results surprised us. On the CORE-Bench test set, A fully solved twenty-nine of thirty tasks, the most of the three, at about one cent per run, the cheapest. On the dev set it solved thirty-two of forty-two. But paired McNemar tests show that none of these differences is significant. |
| 2.6 学到什么 | 一句话：single context → nobody catches a wrong command；failures come from the environment | Its single context is also its weakness: nobody catches a wrong command until the evaluator scores the run. And when A fails, the cause is usually the environment, not the agent. |
| 结尾 | 标题卡 | A simple agent, honestly scored, is a strong baseline. Thank you. |

出处：`SingleAgent/README.md`、`SingleAgent/workflow.py`（max_turns、预算）；`Base/runs/reports/cb_test_summary.md`（29/30、$0.013、p）；`cb_dev_round3_summary.md`（32/42）。

---

# XU YUANHUI · 部分 3 · 工作流 B

## 小组片段 03（25 s）

**画面**：同一个示例任务（capsule-6460826），工作流选 B（fixed）→ 角色卡片按顺序变成 Running / Done（加速）。
念到六个角色名时，画面停在卡片都已出现的时刻。

> Now the same task with Workflow B. Six roles run in a fixed order: Paper Analyst, Env Agent, Planner, Executor and Debugger, Result Reviewer, and Discrepancy Analyst. Each card shows its own model, cost and time. The order is fixed in code, so no role sees the whole picture.

（50 词，约 26 s。超时就删 "Each card shows its own model, cost and time."）

注意：demo 上跑的是 CORE-Bench 任务，B 走的是 spec 版本的角色（Environment Engineer → Planner → Executor ⇄ Debugger → Answerer），
卡片名字和旁白里的论文版六个角色不完全一样。画面上如果名字不同，在画面上加一行小字
"paper runs: 6 roles · CORE-Bench runs: 5 roles"，旁白不用改。

## 个人视频（约 2:35，295 词）

| 节 | 画面 | 旁白 |
|---|---|---|
| 开场 | 标题卡 "Workflow B · fixed pipeline" | Hi, I'm Xu Yuanhui. In Paper2Experiment, I worked on Workflow B, a fixed pipeline of specialised agents. |
| 3.1 B 是什么 | `04-workflows.en.png` 中栏，六个角色框随旁白依次点亮 | Workflow B splits the job among six LLM roles and a deterministic executor. The Paper Analyst reads the paper; the Env Agent installs the environment; the Planner writes the commands; the Executor runs them, with a Debugger to fix failures; a Result Reviewer checks a pilot run; and a Discrepancy Analyst explains any gap with the paper. |
| 3.2 为什么分工 | 每个角色旁边列出它的工具和预算份额；"numbers only from the executor's logs" | The idea is division of labour. Each role sees only the tools it needs and has its own share of the budget, and numbers can only come from the executor's logs, so no role can simply type a result. |
| 3.3 怎么实现 | 路由图：`_next_step` 代码截图；三个标签 "≤ 4 debug sessions" · "1 pilot run per claim" · "checkpoint → p2e resume" | The order is written in code, as a LangGraph state graph, not decided by an LLM. Debugging is capped at four sessions. The reviewer checks one pilot run per claim before the rest of the budget is spent. Every step is checkpointed, so an interrupted run can be resumed where it stopped. |
| 3.4 demo | demo 上 B 跑 capsule-6460826 的录屏（加速） | On the demo site, B shows one card per role. They light up in order, each with its own model, cost and time, until the answers come back next to the paper's values. |
| 3.5 结果 | 表：dev 第 3 轮三组 B 都是 33/42；test 28/30（$0.017/次） | B was the steadiest design: on the dev set it solved thirty-three of forty-two in all three groups, with or without skills, and with either model. On the test set it solved twenty-eight of thirty, at under two cents per run. No difference from A or D is significant. |
| 3.6 弱点 → D | 第一个角色框标红，红色虚线一路指到最后；然后箭头指向 D | Its weakness is structural. Each role sees only its own slice, so a mistake made early, like a command that prints no training progress, is noticed only at the end. That lesson is why we built Workflow D. |
| 结尾 | 标题卡 | Clear roles, fixed order, and honest numbers from logs. Thank you. |

出处：`Multiagent/FixedPipeline/README.md`；`cb_dev_round3_summary.md`（三组 B 均 33）；`cb_test_summary.md`（28/30、$0.017）。

---

# JING KEYING · 部分 5 · 任务和 skill 库

## 小组片段 05（40 s）

**画面**：demo 网站的 Changelog 页面：停在 **Oct 1** → **Oct 16–17**；最后一句切到 `skills/library.yaml`
（`version: 5` / `frozen` / `hash: 7b2f38a06ffceed5` 三行高亮）。Changelog 截图可以直接用
`$K/assets/changelog.png`（2200 px 宽，Oct 1 在 y≈200，Oct 16–17 在 y≈4200）。

> All three workflows share the same tasks. We began with three papers reproduced by hand, which became the hidden ground truth. Then we moved to CORE-Bench, with a dev split to tune on and a test split run once. Every task becomes one ReproSpec. Skills are learned from dev runs: a curator writes lessons, a leak check keeps answers out, and version five was frozen before testing.

（65 词，约 34 s）

## 个人视频（约 2:25，277 词）

| 节 | 画面 | 旁白 |
|---|---|---|
| 开场 | 标题卡 "Tasks & Skill Library" | Hi, I'm Jing Keying. In Paper2Experiment, I worked on the tasks and the skill library that all three workflows share. |
| 5.1 基准任务 | Changelog Oct 1（三篇手工复现）→ Oct 16–17（CORE-Bench dev 45 / test 39）；数字 45 → 39 → 30 | We started with papers we reproduced by hand, so we knew the truth before any agent ran. Seven papers were too few to compare three workflows, so we adopted CORE-Bench, a public benchmark: forty-five capsules as a dev split we could run as often as needed, and thirty-nine as a test split, run only once. For the test, we removed the five capsules we had tried during development and four that need a GPU, leaving thirty. |
| 5.2 ReproSpec | 左右分屏：`Base/benchmark/corebench_v1.1/tasks/cb-0152700/spec.yaml`（agent 看得到）↔ 同目录 `case.yaml`（盖 "HIDDEN"）；箭头标 `corebench.py · to_spec()` | Every task, whether a paper, a capsule or a user's prompt, becomes one shared format: the ReproSpec. A capsule is converted by code, not by an LLM: its run instructions, its language and its questions. The spec the agents see holds no answers. The target values and tolerances go into a separate hidden case file, fixed before any agent runs. |
| 5.3 skill 怎么提炼 | `$K/assets/03-skills-loop.en.png` 四步依次高亮（Digest → Curate → Leak check → Publish）；再切 `skills/CHANGELOG.md` v5 一节，高亮 "read in only 1 of ~75 runs" | Skills are procedures for recurring problems, like setting up R or running old notebooks, never answers. After each dev round, a script digests every run, an LLM curator proposes edits, and a check blocks any task name or value. For example, one macOS rule was read in only one of about seventy-five runs, so it moved into the skill agents open first. |
| 5.4 冻结和效果 | `skills/library.yaml` 三行 → dev 第 3 轮表：D 有 skill 35 / 无 skill 31，A、B 无差别 | Before the test, version five was frozen and hashed, and test runs can never feed the library. Did skills help? Mostly for D: thirty-five tasks with them, thirty-one without. For A and B there was no measurable difference, and Sonnet rarely read them at all. |
| 结尾 | 标题卡 | Shared tasks, hidden answers, and skills that teach procedures, not results. Thank you. |

出处：Changelog（demo 网站）Oct 1、Oct 16–17、Nov 3–4；`Base/p2e/corebench.py`（`to_spec`、`freeze`）；
`Base/p2e/skills.py` 开头说明；`skills/CHANGELOG.md` v5；`skills/library.yaml`；`cb_dev_round3_summary.md` 第 3、4 节。

---

# WANG YIMING · 部分 6 · 实验和展示

## 小组片段 07（40 s）

**画面**：结果表（A 29/30 · B 28/30 · D 26/30，95% CI，每次花费；念到哪个工作流亮哪一行）→ McNemar 配对表
（A vs B p=1.000，A vs D p=0.250，B vs D p=0.625），p 列高亮 → demo 网站：选示例任务、选工作流、实时 agent 图、
答案和论文值的对照表。

> On the CORE-Bench test set, thirty tasks run once, A fully solved twenty-nine, B twenty-eight and D twenty-six. Every workflow ran the same tasks, so we compared them in pairs with an exact McNemar test. Every p-value is at least zero point two five: no architecture is significantly better. And it's all live on our demo site: pick a task and a workflow, watch the agents work, and check each answer against the paper.

（73 词，约 38 s）

## 个人视频（约 2:30，281 词）

| 节 | 画面 | 旁白 |
|---|---|---|
| 开场 | 标题卡 "Experiments & Demo" | Hi, I'm Wang Yiming. In Paper2Experiment, I ran the experiments and presented them on our demo website. |
| 6.1 实验设计 | 架构图，"only the workflow changes"；时间线：dev 第 1、2、3 轮（第 3 轮 405 次）→ 冻结 → test 一次 | A fair comparison needs everything but the workflow fixed: the same tasks, sandbox, models, skills and evaluator. We tuned on the CORE-Bench dev split over three rounds, four hundred and five runs in the last one alone, then froze code and skills and ran the test split exactly once. |
| 6.2 结果表 | 表：A 29/30（83–99%）、B 28/30（79–98%）、D 26/30（70–95%），总花费 $1.65 | On the test set, thirty tasks and ninety runs, A fully solved twenty-nine, B twenty-eight, and D twenty-six, for one dollar sixty-five in total. With only thirty tasks, the ninety-five percent confidence intervals are wide: D's runs from seventy to ninety-five percent. |
| 6.3 McNemar | 配对表：都对 / 只有前者对 / 只有后者对 / 都错；A vs D 一行 26 · 3 · 0 · 1 高亮，p = 0.25 | Because all three workflows ran the same tasks, we compare them in pairs. The exact McNemar test looks only at tasks where one workflow passed and the other failed. A against D: three such tasks, all won by A, which gives p equals zero point two five. Every pair is at least that high, so no difference is significant. |
| 6.4 dev 和 test | dev 第 3 轮 D 第一（35/42）↔ test D 最后（26/30）；Haiku $2.19 vs Sonnet $16.72，都是 100/126 | The ranking also flipped: D led on the dev set and came last on the test set, within noise both times. And Sonnet cost seven point six times more than Haiku for exactly the same score, so the bottleneck is the environment, not the model. |
| 6.5 demo 网站 | demo 录屏：输入框 / 示例任务 → 选工作流和模型 → 实时 agent 图 → 结果对照表 → History、Changelog 菜单 | You can try it yourself on our demo site. Describe a task or pick an example, choose a workflow and a model, and watch the agents work as a live graph. At the end, each answer is shown next to the value the paper reports. A history and a changelog record every run and every change. |
| 结尾 | 标题卡 + demo 网址 paper2experiment.allenhu.com | Same tasks, honest statistics, and a demo anyone can run. Thank you. |

出处：`Base/runs/reports/cb_test_summary.md`（结果、Wilson CI、McNemar 表、$1.65）；`cb_dev_round3_summary.md`
（405 次、Sonnet 7.6 倍、D 35/42）；Changelog Nov 6–7（demo 功能）。
