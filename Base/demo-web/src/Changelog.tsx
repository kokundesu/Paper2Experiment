// The project's changelog, oldest first, on the 21st.dev Timeline (vendor/21st/timeline.tsx): how the system was built,
// why its agents are the ones they are, the experiment rounds, the agent evaluations and what changed between them.
// The facts come from docs/corebench-inventory.md, Base/docs/* and Base/runs/reports/*; the figures are in
// changelog/diagrams.tsx. ENTRIES is the English text and ENTRIES_ZH the Chinese one; the site's language picks one.
import {ArrowLeft} from 'lucide-react';
import type {ReactNode} from 'react';
import {Timeline} from './vendor/21st/timeline';
import {FigureComparison, FigureGrading, FigurePipelineV2, FigurePlannerLoop, FigureWorkflows} from './changelog/diagrams';
import {useLang} from './i18n';

function P({children}: {children: ReactNode}) {
  return <p className="text-neutral-800 dark:text-neutral-200 text-sm md:text-base font-normal mb-4 leading-relaxed">{children}</p>;
}

function H({children}: {children: ReactNode}) {
  return <h4 className="text-neutral-900 dark:text-neutral-100 text-sm md:text-base font-semibold mt-6 mb-2">{children}</h4>;
}

function Stats({items}: {items: [string, string][]}) {
  return <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
    {items.map(([k, v]) => <div key={k} className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{k}</div>
      <div className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 tabular-nums">{v}</div>
    </div>)}
  </div>;
}

function Bullets({items}: {items: ReactNode[]}) {
  return <ul className="mb-6 space-y-1.5">
    {items.map((it, i) => <li key={i} className="flex gap-2 text-sm text-neutral-700 dark:text-neutral-300 leading-relaxed">
      <span className="mt-[9px] h-1.5 w-1.5 flex-none rounded-full bg-neutral-400 dark:bg-neutral-600"/><span>{it}</span></li>)}
  </ul>;
}

function Table({head, rows}: {head: string[]; rows: ReactNode[][]}) {
  return <div className="mb-6 overflow-x-auto rounded-xl border border-neutral-200 dark:border-neutral-800">
    <table className="w-full text-sm">
      <thead className="bg-neutral-50 dark:bg-neutral-900 text-neutral-500"><tr>{head.map(h => <th key={h} className="px-3 py-2 text-left font-medium whitespace-nowrap">{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-neutral-200 dark:border-neutral-800">
        {r.map((c, j) => <td key={j} className={`px-3 py-2 align-top text-neutral-800 dark:text-neutral-200 ${j ? 'tabular-nums' : 'font-medium whitespace-nowrap'}`}>{c}</td>)}</tr>)}</tbody>
    </table>
  </div>;
}

const ENTRIES = [
  {title: 'Oct 1, 2026', content: <>
    <P><b>Day one: ground truth before agents.</b> Three engineering papers were reproduced by hand first (GCN, L2O-WMMSE,
      PINN Burgers), each judged full against the paper, with every trap written down: packages renamed, a default seed
      that happens to be the worst one, a <code>test.py</code> that loads pretrained weights and prints a paper-like number
      without training. Those records became the benchmark’s hidden <code>case.yaml</code> and the evaluator was calibrated
      on the manual logs: 3 of 3 judged full, the same as the people.</P>
    <P>Three frameworks were written against it: a deterministic baseline (clone, install, run the README command, grep the
      number, no LLM), a single agent with every tool, and a multi-agent pipeline. The design rules that survived every
      later version were set here:</P>
    <Bullets items={[
      <><b>The truth is hidden.</b> Agents see <code>task.yaml</code> only; the sandbox blocks reads of <code>case.yaml</code> and the benchmark folder.</>,
      <><b>Numbers come from logs.</b> A submitted value must appear in the log it cites; evidence patterns demand the training trace, so loading pretrained weights is not a reproduction.</>,
      <><b>Tolerance per claim, justified in writing;</b> a hard dollar budget per run on a shared ledger; every run leaves <code>trace.jsonl</code> and full command logs.</>,
    ]}/>
  </>},
  {title: 'Oct 4–5, 2026', content: <>
    <P><b>Why these agents: the multi-agent pipeline grows roles as the papers break it.</b> Seven hand-built cases now (DLinear,
      KalmanNet, SGC and FITS added). Each new paper exposed a failure the single agent could not see from inside its own
      context, and each got a role whose only job is to see it:</P>
    <Table head={['Version', 'Added', 'Because']} rows={[
      ['v0', 'Paper Analyst · Env Agent · Planner · Executor', 'The baseline split: read, install, plan, and an executor that is code so numbers can only come from logs'],
      ['v0.1', 'Discrepancy Analyst', 'A failed claim was reported as a number, never as a cause; a reader wants to know why'],
      ['v0.2', 'Result Reviewer, evidence rules, log integrity', 'Runs that printed nothing, or the wrong metric, were counted; the reviewer checks one pilot run per claim before the rest are spent'],
      ['v1', '“2–3 % counts as agreement”, reviewers at high effort', 'Seed noise alone failed claims that any human would call reproduced'],
      ['v2', 'Pre-registered criteria, conflict rules, one value per seed', 'The judgement must be fixed before the run, and the same for both workflows'],
    ]}/>
    <FigurePipelineV2/>
    <H>What the comparison said</H>
    <Stats items={[['single, v2', '13 / 15'], ['multi, v2', '14 / 15'], ['false successes', '0 of 48'], ['multi cost', '1.4× single']]}/>
    <P>Five cases × two workflows × three repeats. No stable winner: the whole gap sat in KalmanNet, where the runs that inferred
      the unstated noise level passed and the others failed, in both workflows. Both were honest (no false success, no false
      alarm in 48 runs); the multi-agent diagnoses went deeper but rarely found the mechanism. The structural weakness of the
      pipeline was already visible: no role has global oversight, so an upstream mistake is caught only by the evaluator at
      the end.</P>
  </>},
  {title: 'Oct 16–17, 2026', content: <>
    <P><b>Benchmark redesign: borrow the dataset, keep the rules.</b> Thirteen reproduction benchmarks were compared. Seven
      hand-built papers cannot separate three workflows, and every tuning round on them leaks. CORE-Bench was adopted as the
      external dataset: the original train set (45 capsules) as a dev split that may be run as often as needed, and v1.1
      mainline (39 capsules) as a test split to be run once, after code and skills are frozen. Nothing in it was chosen by us.</P>
    <FigureGrading/>
    <Bullets items={[
      <><b>Tolerance per question:</b> the prediction interval of the three manual re-runs, or half a unit of the last printed digit, or 1e-5 relative, whichever is widest; a question noisier than 5 % of its mean is unscored, not failed.</>,
      <><b>ReproSpec:</b> one task format whether the source is a user’s prompt, a CORE-Bench capsule or a hand-built case; the workflows read its brief and submit <code>Answers</code>; only the evaluator knows the values.</>,
      <><b>Provenance:</b> an answer counts only if this run produced it. Typed values, files the capsule shipped and anything inside an installed environment do not count. This is the check that makes shortcuts worthless.</>,
      <>The original HAL grading rule is kept alongside so the numbers can be compared with published ones.</>,
    ]}/>
  </>},
  {title: 'Oct 17–18, 2026', content: <>
    <P><b>Dev round 1 and the agent evaluation.</b> The first 20 Python tasks of the dev split, each run by the three workflows
      that are compared from here on. <code>agenteval</code> turns a batch of runs into a report: pass rates with Wilson
      intervals, paired exact McNemar tests between workflows, a failure taxonomy (setup, budget, no answers, provenance, wrong
      answers), and which skills each run read.</P>
    <FigureWorkflows/>
    <H>Why D was built</H>
    <P>B’s weakness is structural: each role sees its own slice, and a bad command upstream is noticed at the very end. D answers
      it with one Planner that sees everything, but is not allowed to run anything: a deterministic runtime holds the task
      graph, executes commands, and decides when the run is over. The ideas are borrowed on purpose: a single planner with
      declarative patches and the runtime as source of truth (DeepSeek Harness / Cuti), verification at several stages where
      only the verifier ends a run (MAST), task and progress ledgers with stall-triggered re-planning (Magentic-One), a dry
      run before the real one (AutoReproduce), and isolated worker contexts (Anthropic’s research system).</P>
    <FigurePlannerLoop/>
    <Bullets items={[
      <><b>Workers are fresh.</b> Each agent task (setup, debug, diagnose) is a delegation with objective, boundaries, done criteria and a budget share; the worker sees nothing else and returns a typed report. Workers never talk to each other.</>,
      <><b>Three gates, all code:</b> a plan check when a run is added (no piping output into filters), a smoke run of the cut-down command, an evidence check of the full log. On capsules, a fourth gate refuses a finish whose answers the run did not produce.</>,
      <><b>Replacements keep their lineage:</b> a retried task is a new task that replaces the failed one, dependants are rewired, and a lineage gets at most three attempts.</>,
      <>Ablations kept for the appendix: C (agent tasks in the Planner’s own context) and C- (no gates either).</>,
    ]}/>
    <Stats items={[['A', '13 / 17'], ['B', '12 / 17'], ['D', '13 / 17'], ['skills', 'v2 · 7']]}/>
    <P>Also decided here: R environments with micromamba inside the workspace, a <code>view_image</code> tool for every agent, and
      8-way parallel capsule downloads. After the round, the Hard-level clean-up was redefined as in the CORE-Bench paper (data and
      checkpoints stay; only results, the run script, the environment spec and the instructions go), and a task whose every
      question is too noisy is unscored rather than failed.</P>
  </>},
  {title: 'Oct 18–19, 2026', content: <>
    <P><b>Dev round 2: all 45 tasks, 135 runs,</b> Python and R, figure questions included, skill library v4. Two evaluation
      bugs were found by reading the reports, not the code:</P>
    <Stats items={[['A', '32 / 42'], ['B', '34 / 42'], ['D', '34 / 42'], ['unscored', '3 tasks']]}/>
    <Bullets items={[
      <><b>The leak check flagged ordinary words.</b> A task identifier that is also an English word (“fits”) was treated as a leak, so a whole round of skill curation had been silently dropped. Fixed with a dictionary; the curation re-applied gives library v5.</>,
      <><b>Provenance searched the R environment.</b> Answers were being “found” in thousands of files under <code>.renv</code>. Excluded from round 3 on; round 2 could not be rescored because its workspaces were gone.</>,
    ]}/>
  </>},
  {title: 'Oct 27, 2026', content: <>
    <P><b>Operations for long batches.</b> Round 3 would be 405 runs on a 16 GB laptop, so the batch runner learned to survive:
      <code>--skip-done</code> resumes from the finished runs; <code>--jobs N</code> runs tasks in parallel, each with its own uv
      and micromamba caches; <code>caffeinate</code> keeps the Mac awake; disk guards clear caches under 6 GB free and stop under
      4 GB; <code>P2E_SKILLS=off</code> gives the no-skill control group.</P>
    <Bullets items={[
      <>Text in PDF figures is extracted, so an axis label read off a generated PDF counts as produced.</>,
      <>Dependencies pinned in <code>uv.lock</code>; unscored tasks reported under the HAL rule too.</>,
    ]}/>
  </>},
  {title: 'Oct 27 – Nov 1, 2026', content: <>
    <P><b>Dev round 3: three groups, 405 runs.</b> Haiku 5.5 with skills v5, Sonnet 5.5 with v5, and Haiku with skills off, on all
      45 tasks × A, B, D. Two tasks in parallel; interrupted three times (a kernel panic, an OS update, swap filling the disk)
      and resumed each time with <code>--skip-done</code>.</P>
    <Table head={['Group', 'A', 'B', 'D', 'Cost']} rows={[['Haiku · v5', 32, 33, 35, '$2.19'], ['Sonnet · v5', 31, 33, 36, '$16.72'], ['Haiku · no skills', 31, 33, 31, '$2.39']]}/>
    <Bullets items={[
      <><b>Model:</b> Sonnet matched Haiku exactly (100 vs 100 of 126) at 7.6× the cost; the bottleneck is whether the environment can be built and the code run, not the model. Haiku stays.</>,
      <><b>Skills:</b> 100 vs 95 with them off; only D benefits (35 vs 31). Sonnet barely reads them.</>,
      <><b>Library:</b> v5 equals v4 on dev (100 / 126 each), so v5 was frozen as is rather than upgraded again.</>,
    ]}/>
  </>},
  {title: 'Nov 1, 2026', content: <>
    <P><b>Figure questions scored fairly.</b> Three figure questions were right in every group yet judged “not found”: the agent
      had opened the generated PNG with <code>view_image</code> and read the answer off it, and a PNG holds no text. The rule
      now: a correct figure answer found in no text counts as produced if the run viewed an image it made (not in the baseline
      snapshot, or changed). Every earlier run was rescored offline from its snapshot and trace; 14 round-3 runs moved from
      partial to full, rounds 1 and 2 did not change. The same rule sits in the scorer and in D’s finish gate.</P>
  </>},
  {title: 'Nov 3–4, 2026', content: <>
    <P><b>The test split, once.</b> Skill library v5 frozen (hash <code>7b2f38a06ffceed5</code>); the five capsules piloted during
      development and the four GPU tasks removed; the remaining 30 CPU tasks of CORE-Bench v1.1 mainline run with A, B and D on
      Haiku 5.5: 90 runs in 8 h 50 min for $1.65.</P>
    <Stats items={[['A · single', '29 / 30'], ['B · fixed', '28 / 30'], ['D · planner', '26 / 30'], ['McNemar p', '≥ 0.25']]}/>
    <FigureComparison/>
    <P>The test split is easier than dev (1.5 questions per task against 2.3; 27 of 30 tasks passed by all three workflows), and the
      ranking from dev did not carry over: D led on dev and trails on test, within noise both times. Across all rounds the three
      workflows are indistinguishable at this sample size; what separates runs is the environment, not the orchestration. One D
      failure on the test split was a harness bug (a Planner replacing a task it never added), fixed with a regression test.</P>
  </>},
  {title: 'Nov 6–7, 2026', content: <>
    <P><b>The demo.</b> An agent chat: a request becomes a task in one LLM call, a second call reads the arXiv paper for the values
      each question should reproduce, the chosen workflow runs the task, and the answers come back in a table against the paper.
      The run is a live graph of agents with the step each one is on, fed by the same trace the evaluations read.</P>
    <Bullets items={[
      'A multi-agent orchestration graph (cards, connectors, step branches) laid out from the run; the AgentRun panel, model picker, loader and shining text reused from Alex.',
      'Example tasks: every CORE-Bench task an earlier run answered in under 10 minutes, run again from scratch with any workflow and model, graded by the benchmark’s own grader.',
      'A run folder chosen from the page, a history of runs, this changelog; a harness bug found through the demo and fixed with a regression test.',
    ]}/>
  </>},
];

// The same entries in Chinese: same dates, order, components and markup.
const ENTRIES_ZH = [
  {title: '2026年 10月1日', content: <>
    <P><b>第一天：先定真值，再上 agent。</b>先手工复现了三篇工程论文（GCN、L2O-WMMSE、PINN Burgers），对照论文每篇都判为
      full，并把遇到的每个坑都记了下来：包改了名；默认 seed 恰好是最差的那个；还有一个 <code>test.py</code> 会加载预训练权重，
      不训练就打印出一个和论文差不多的数字。这些记录成了 benchmark 中隐藏的 <code>case.yaml</code>，evaluator 也用这些手工日志做了
      校准：3 篇中 3 篇判为 full，和人工的结论一致。</P>
    <P>在此基础上写了三套框架：一个确定性的 baseline（clone、安装、运行 README 里的命令、grep 出数字，完全不用 LLM），一个拥有全部
      工具的单 agent，以及一条多 agent pipeline。之后每个版本都沿用下来的设计规则，就是在这时定下的：</P>
    <Bullets items={[
      <><b>真值是隐藏的。</b>agent 只能看到 <code>task.yaml</code>；sandbox 禁止读取 <code>case.yaml</code> 和 benchmark 文件夹。</>,
      <><b>数字来自日志。</b>提交的数值必须出现在它所引用的日志里；证据规则要求有训练过程的 trace，所以加载预训练权重不算复现。</>,
      <><b>每条 claim 单独设容差，并书面写明理由；</b>每次运行都有硬性的美元预算，记在一本共享账本上；每次运行都会留下 <code>trace.jsonl</code> 和完整的命令日志。</>,
    ]}/>
  </>},
  {title: '2026年 10月4–5日', content: <>
    <P><b>为什么是这些 agent：多 agent pipeline 的角色，是被一篇篇论文“逼”出来的。</b>手工构建的 case 增加到七个（新增 DLinear、
      KalmanNet、SGC 和 FITS）。每篇新论文都暴露出一种单 agent 在自己的上下文里看不到的失败，于是每种失败都配了一个角色，它唯一的
      任务就是发现这种失败：</P>
    <Table head={['版本', '新增', '原因']} rows={[
      ['v0', 'Paper Analyst · Env Agent · Planner · Executor', '基本分工：阅读、安装、规划，再加一个用代码实现的 executor，这样数字只能来自日志'],
      ['v0.1', 'Discrepancy Analyst', '失败的 claim 只会被报告成一个数字，从不给出原因；而读者想知道的是为什么'],
      ['v0.2', 'Result Reviewer、证据规则、日志完整性检查', '什么都没打印、或打印了错误指标的运行也被计入了；reviewer 会先检查每条 claim 的一次 pilot 运行，再花掉其余的预算'],
      ['v1', '“2–3 % 以内算一致”，reviewer 用 high effort', '光是 seed 噪声就让一些 claim 判为失败，而任何人都会认为它们已经复现了'],
      ['v2', '预注册的判据、冲突规则、每个 seed 一个值', '判断标准必须在运行之前定好，并且两种 workflow 用同一套'],
    ]}/>
    <FigurePipelineV2/>
    <H>对比结果说明了什么</H>
    <Stats items={[['single，v2', '13 / 15'], ['multi，v2', '14 / 15'], ['假成功', '48 次中 0 次'], ['multi 成本', 'single 的 1.4×']]}/>
    <P>五个 case × 两种 workflow × 三次重复。没有稳定的赢家：全部差距都集中在 KalmanNet 上——推断出论文没写明的噪声水平的运行通过了，
      没推断出来的就失败了，两种 workflow 都是如此。两者都是诚实的（48 次运行中既没有假成功，也没有误报）；多 agent 的诊断挖得更深，
      但很少找到真正的机制。pipeline 的结构性弱点这时已经显现出来：没有哪个角色拥有全局视角，所以上游的错误只能等到最后由 evaluator
      发现。</P>
  </>},
  {title: '2026年 10月16–17日', content: <>
    <P><b>重新设计 benchmark：借用数据集，保留规则。</b>比较了十三个复现类 benchmark。七篇手工构建的论文不足以区分三种 workflow，而且
      在它们上面每调一轮都会泄漏信息。于是采用 CORE-Bench 作为外部数据集：原始训练集（45 个 capsule）作为 dev split，想跑多少次都
      可以；v1.1 mainline（39 个 capsule）作为 test split，等代码和 skill 冻结之后只跑一次。其中没有任何东西是我们自己挑的。</P>
    <FigureGrading/>
    <Bullets items={[
      <><b>每道题单独设容差：</b>取三次人工重跑的预测区间、最后一位打印数字的半个单位、1e-5 相对误差三者中最宽的那个；噪声超过均值 5 % 的题目不计分，而不是判为失败。</>,
      <><b>ReproSpec：</b>统一的任务格式，无论来源是用户的 prompt、CORE-Bench 的 capsule，还是手工构建的 case；workflow 读取其中的 brief 并提交 <code>Answers</code>；只有 evaluator 知道真实数值。</>,
      <><b>Provenance（来源）：</b>只有本次运行产出的答案才算数。手打进去的数值、capsule 自带的文件、已安装环境里的任何东西都不算。正是这项检查让走捷径变得毫无用处。</>,
      <>同时保留了 HAL 原本的评分规则，方便和已发表的数字做比较。</>,
    ]}/>
  </>},
  {title: '2026年 10月17–18日', content: <>
    <P><b>Dev 第 1 轮与 agent 评估。</b>取 dev split 的前 20 个 Python 任务，每个任务都用此后一直拿来比较的三种 workflow 各跑一遍。
      <code>agenteval</code> 把一批运行整理成一份报告：带 Wilson 区间的通过率、workflow 之间两两配对的精确 McNemar 检验、失败分类
      （环境配置、预算、没有答案、来源、答案错误），以及每次运行读了哪些 skill。</P>
    <FigureWorkflows/>
    <H>为什么要做 D</H>
    <P>B 的弱点是结构性的：每个角色只看到自己那一块，上游的一条错误命令要到最后才会被发现。D 的回应是只设一个能看到全局的 Planner，
      但不允许它执行任何东西：由一个确定性的 runtime 持有任务图、执行命令，并决定运行何时结束。这些想法都是有意借鉴的：单一 planner
      用声明式 patch、以 runtime 为事实来源（DeepSeek Harness / Cuti）；在多个阶段做验证，并且只有 verifier 能结束运行（MAST）；任务
      ledger 和进度 ledger，停滞时触发重新规划（Magentic-One）；正式运行前先 dry run 一遍（AutoReproduce）；以及相互隔离的 worker
      上下文（Anthropic 的 research system）。</P>
    <FigurePlannerLoop/>
    <Bullets items={[
      <><b>Worker 每次都是全新的。</b>每个 agent 任务（环境配置、调试、诊断）都是一次委派，写明目标、边界、完成标准和分到的预算份额；worker 除此之外什么都看不到，最后返回一份有类型的报告。worker 之间从不相互通信。</>,
      <><b>三道 gate（关卡），全部是代码：</b>添加运行时做计划检查（不允许把输出用管道接到过滤命令上），对缩减版命令做一次 smoke run，对完整日志做证据检查。在 capsule 上还有第四道 gate：如果结束请求里的答案不是本次运行产出的，就拒绝结束。</>,
      <><b>替代任务保留谱系：</b>重试的任务是一个新任务，用来替换失败的那个，依赖它的任务会重新接过去；每条谱系最多尝试三次。</>,
      <>留作附录的消融：C（agent 任务在 Planner 自己的上下文里执行）和 C-（连 gate 也没有）。</>,
    ]}/>
    <Stats items={[['A', '13 / 17'], ['B', '12 / 17'], ['D', '13 / 17'], ['skills', 'v2 · 7']]}/>
    <P>这一阶段还定下了：R 环境用 micromamba 装在 workspace 里面，每个 agent 都配一个 <code>view_image</code> 工具，capsule 下载 8 路
      并行。这一轮结束后，Hard 难度的清理方式按 CORE-Bench 论文重新定义（数据和 checkpoint 保留；只删掉结果、运行脚本、环境说明和
      使用说明），并且所有题目噪声都过大的任务改为不计分，而不是判为失败。</P>
  </>},
  {title: '2026年 10月18–19日', content: <>
    <P><b>Dev 第 2 轮：全部 45 个任务，135 次运行，</b>Python 和 R 都有，包括看图题，skill 库 v4。发现了两个评估 bug，都是读报告读出来
      的，而不是读代码：</P>
    <Stats items={[['A', '32 / 42'], ['B', '34 / 42'], ['D', '34 / 42'], ['不计分', '3 个任务']]}/>
    <Bullets items={[
      <><b>泄漏检查把普通单词当成了泄漏。</b>一个同时也是英文单词的任务标识符（“fits”）被当成了泄漏，结果一整轮 skill 整理被悄无声息地丢掉了。用词典修复后，重新应用这轮整理，得到 skill 库 v5。</>,
      <><b>来源检查搜进了 R 环境。</b>答案在 <code>.renv</code> 下成千上万个文件里被“找到”。从第 3 轮起把它排除；第 2 轮无法重新评分，因为它的 workspace 已经不在了。</>,
    ]}/>
  </>},
  {title: '2026年 10月27日', content: <>
    <P><b>为长批次做的运维。</b>第 3 轮要在一台 16 GB 内存的笔记本上跑 405 次，所以 batch runner 学会了“活下去”：
      <code>--skip-done</code> 从已完成的运行处续跑；<code>--jobs N</code> 并行跑多个任务，每个任务有自己的 uv 和 micromamba 缓存；
      <code>caffeinate</code> 让 Mac 保持唤醒；磁盘保护在剩余空间不足 6 GB 时清理缓存、不足 4 GB 时停止；<code>P2E_SKILLS=off</code>
      提供不用 skill 的对照组。</P>
    <Bullets items={[
      <>PDF 图中的文字会被提取出来，所以从生成的 PDF 上读到的坐标轴标签也算作本次运行产出。</>,
      <>依赖固定在 <code>uv.lock</code> 里；不计分的任务也按 HAL 规则报告。</>,
    ]}/>
  </>},
  {title: '2026年 10月27日 – 11月1日', content: <>
    <P><b>Dev 第 3 轮：三组，405 次运行。</b>Haiku 5.5 配 skill v5、Sonnet 5.5 配 v5、Haiku 关闭 skill，在全部 45 个任务 × A、B、D 上
      运行。两个任务并行；中途被打断三次（一次 kernel panic、一次系统更新、一次 swap 把磁盘占满），每次都用 <code>--skip-done</code>
      续跑。</P>
    <Table head={['组别', 'A', 'B', 'D', '成本']} rows={[['Haiku · v5', 32, 33, 35, '$2.19'], ['Sonnet · v5', 31, 33, 36, '$16.72'], ['Haiku · 无 skill', 31, 33, 31, '$2.39']]}/>
    <Bullets items={[
      <><b>模型：</b>Sonnet 与 Haiku 完全打平（126 个中都是 100 个），成本却是 7.6 倍；瓶颈在于环境能不能搭起来、代码能不能跑通，而不在模型。继续用 Haiku。</>,
      <><b>Skill：</b>开启时 100，关闭时 95；只有 D 从中受益（35 对 31）。Sonnet 几乎不读 skill。</>,
      <><b>Skill 库：</b>v5 在 dev 上与 v4 持平（各为 100 / 126），所以 v5 按原样冻结，不再继续升级。</>,
    ]}/>
  </>},
  {title: '2026年 11月1日', content: <>
    <P><b>看图题得到公平评分。</b>有三道看图题在每一组里都答对了，却被判为“未找到”：agent 用 <code>view_image</code> 打开了生成的
      PNG，从图上读出了答案，而 PNG 里没有任何文字。现在的规则是：一个正确的看图题答案如果在任何文本里都找不到，但本次运行查看过一张
      自己生成的图片（不在 baseline 快照里，或者被改动过），就算作本次运行产出。之前的所有运行都根据各自的快照和 trace 离线重新评分；
      第 3 轮有 14 次运行从 partial 变成了 full，第 1、2 轮没有变化。同一条规则同时写在评分器和 D 的 finish gate 里。</P>
  </>},
  {title: '2026年 11月3–4日', content: <>
    <P><b>Test split，只跑一次。</b>skill 库 v5 冻结（hash <code>7b2f38a06ffceed5</code>）；去掉开发期间试跑过的五个 capsule 和四个 GPU
      任务；CORE-Bench v1.1 mainline 剩下的 30 个 CPU 任务用 A、B、D 在 Haiku 5.5 上运行：90 次运行，耗时 8 小时 50 分钟，花费 $1.65。</P>
    <Stats items={[['A · 单 agent', '29 / 30'], ['B · 固定 pipeline', '28 / 30'], ['D · planner', '26 / 30'], ['McNemar p', '≥ 0.25']]}/>
    <FigureComparison/>
    <P>test split 比 dev 简单（每个任务平均 1.5 道题，dev 是 2.3 道；30 个任务中有 27 个三种 workflow 都通过了），dev 上的排名也没有
      延续下来：D 在 dev 上领先、在 test 上落后，两次都在噪声范围之内。综合所有轮次，在这个样本量下三种 workflow 无法区分；真正把
      运行区分开的是环境，而不是编排方式。test split 上 D 的一次失败是 harness 的 bug（Planner 替换了一个它从未添加过的任务），已经
      修复并补了回归测试。</P>
  </>},
  {title: '2026年 11月6–7日', content: <>
    <P><b>Demo。</b>一个 agent 聊天界面：一次 LLM 调用把请求变成一个任务，第二次调用读取 arXiv 论文，找出每道题应当复现出的数值，所选的
      workflow 运行这个任务，答案以表格形式返回，并与论文中的数值对照。运行过程显示为一张实时的 agent 图，标出每个 agent 当前所处的
      步骤，数据来自评估时读取的同一份 trace。</P>
    <Bullets items={[
      '一张多 agent 编排图（卡片、连接线、步骤分支），按运行过程自动布局；AgentRun 面板、模型选择器、加载动画和闪光文字复用自 Alex。',
      '示例任务：此前某次运行在 10 分钟内答完的所有 CORE-Bench 任务，可以用任意 workflow 和模型从头再跑一遍，并由 benchmark 自带的评分器评分。',
      '可以在页面上选择运行目录，有运行历史，还有这份更新日志；通过 demo 发现了一个 harness bug，已经修复并补了回归测试。',
    ]}/>
  </>},
];

export function ChangelogPage({onBack}: {onBack: () => void}) {
  const {lang, L} = useLang();
  return <div className="changelog-page">
    <div className="changelog-bar">
      <button type="button" className="btn ghost sm" onClick={onBack}><ArrowLeft size={14}/>{L('Back to the chat', '返回聊天')}</button>
    </div>
    <Timeline data={lang === 'zh' ? ENTRIES_ZH : ENTRIES} title={L('Changelog', '更新日志')}
      description={L('Paper2Exp from the first manual reproduction to the frozen test run: how the agents came to be what they are, the experiment rounds, the agent evaluations and what changed between them.',
        'Paper2Exp 从第一次手工复现到冻结后的 test 运行：agent 是怎样变成现在这个样子的，各轮实验、agent 评估，以及每一轮之间改了什么。')}/>
  </div>;
}
