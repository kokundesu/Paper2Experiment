// The project's changelog, oldest first, on the 21st.dev Timeline (vendor/21st/timeline.tsx): how the system was built,
// why its agents are the ones they are, the experiment rounds, the agent evaluations and what changed between them.
// The facts come from docs/corebench-inventory.md, Base/docs/* and Base/runs/reports/*; the figures are in
// changelog/diagrams.tsx.
import {ArrowLeft} from 'lucide-react';
import type {ReactNode} from 'react';
import {Timeline} from './vendor/21st/timeline';
import {FigureComparison, FigureGrading, FigurePipelineV2, FigurePlannerLoop, FigureWorkflows} from './changelog/diagrams';

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

export function ChangelogPage({onBack}: {onBack: () => void}) {
  return <div className="changelog-page">
    <div className="changelog-bar">
      <button type="button" className="btn ghost sm" onClick={onBack}><ArrowLeft size={14}/>Back to the chat</button>
    </div>
    <Timeline data={ENTRIES} title="Changelog"
      description="Paper2Exp from the first manual reproduction to the frozen test run: how the agents came to be what they are, the experiment rounds, the agent evaluations and what changed between them."/>
  </div>;
}
