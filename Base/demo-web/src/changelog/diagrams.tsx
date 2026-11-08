// Diagrams for the changelog, drawn by the rules of the diagram-design skill (github.com/cathrynlavery/diagram-design):
// inline SVG in its default editorial skin (paper / ink / muted / one accent), node boxes at rx=6 with a rectangular
// type tag, orthogonal connectors with r=8 elbows and masked labels, arrows drawn before boxes, a legend strip at the
// bottom, at most 9 nodes and 1–2 accented elements per figure. Colors are CSS variables (app.css, --dg-*) so the
// dark skin applies under .dark. Every label is written in both languages, L('English', '中文'); the geometry is the same
// for both, and mask and legend widths are measured with textW so that Chinese characters (about 1 em wide) fit.
import type {ReactNode} from 'react';
import {useLang} from '../i18n';

const R = 8;
const C = {paper: 'var(--dg-paper)', paper2: 'var(--dg-paper-2)', ink: 'var(--dg-ink)', muted: 'var(--dg-muted)', soft: 'var(--dg-soft)',
  rule: 'var(--dg-rule)', accent: 'var(--dg-accent)', accentTint: 'var(--dg-accent-tint)', link: 'var(--dg-link)'};
const SANS = 'Geist, system-ui, sans-serif';
const MONO = '"Geist Mono", ui-monospace, monospace';

/** Estimated width of a label: `ascii` px per narrow character, `cjk` px per CJK or full-width one. For an English label this
 *  is exactly label.length * ascii, so the English figures are unchanged. */
const WIDE = /[\u2E80-\u9FFF\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFF60\uFFE0-\uFFE6\u3000-\u303F]/;
function textW(s: string, ascii: number, cjk: number) {
  let w = 0;
  for (const ch of s) w += WIDE.test(ch) ? cjk : ascii;
  return w;
}

type Kind = 'focal' | 'step' | 'store' | 'input' | 'optional';
const FILL: Record<Kind, {fill: string; stroke: string; dash?: string}> = {
  focal: {fill: C.accentTint, stroke: C.accent}, step: {fill: C.paper, stroke: C.ink}, store: {fill: C.paper2, stroke: C.ink},
  input: {fill: C.paper, stroke: C.muted}, optional: {fill: C.paper, stroke: C.muted, dash: '4,3'},
};

/** A node box: paper mask, the box, a type tag, the name in sans, a mono sublabel. */
function Node({x, y, w = 128, h = 48, tag, name, sub, kind = 'step'}: {x: number; y: number; w?: number; h?: number; tag?: string; name: string; sub?: string; kind?: Kind}) {
  const f = FILL[kind];
  return <g>
    <rect x={x} y={y} width={w} height={h} rx={6} fill={C.paper}/>
    <rect x={x} y={y} width={w} height={h} rx={6} fill={f.fill} stroke={f.stroke} strokeWidth={kind === 'focal' ? 1.4 : 1.1} strokeDasharray={f.dash}/>
    {tag && <>
      <rect x={x + 8} y={y + 7} width={tag.length * 5.3 + 8} height={11} rx={2} fill={kind === 'focal' ? C.accent : C.ink} opacity={kind === 'focal' ? 1 : 0.85}/>
      <text x={x + 12} y={y + 15} fontFamily={MONO} fontSize={7} fontWeight={500} letterSpacing="0.14em" fill={C.paper}>{tag.toUpperCase()}</text>
    </>}
    <text x={x + 8} y={y + (tag ? 31 : 23)} fontFamily={SANS} fontSize={12} fontWeight={600} fill={kind === 'focal' ? C.accent : C.ink}>{name}</text>
    {sub && <text x={x + 8} y={y + (tag ? 42 : 35)} fontFamily={MONO} fontSize={8.5} fill={C.soft}>{sub}</text>}
  </g>;
}

/** A zone behind a group of nodes, its eyebrow on a paper mask. */
function Zone({x, y, w, h, label}: {x: number; y: number; w: number; h: number; label: string}) {
  return <g>
    <rect x={x} y={y} width={w} height={h} rx={8} fill={C.ink} fillOpacity={0.025} stroke={C.ink} strokeOpacity={0.12} strokeWidth={0.8}/>
    <rect x={x + 10} y={y + 4} width={textW(label, 5.4, 8.2) + 10} height={12} rx={2} fill={C.paper}/>
    <text x={x + 15} y={y + 13} fontFamily={MONO} fontSize={7} fontWeight={500} letterSpacing="0.14em" fill={C.soft}>{label}</text>
  </g>;
}

/** A connector: a straight line on a shared axis, else a two-bend elbow at r=8 through the midpoint (horizontal first). */
function elbow(x1: number, y1: number, x2: number, y2: number) {
  if (Math.abs(y1 - y2) < 1 || Math.abs(x1 - x2) < 1) return `M ${x1},${y1} L ${x2},${y2}`;
  const mid = (x1 + x2) / 2, sx = x2 > x1 ? 1 : -1, sy = y2 > y1 ? 1 : -1;
  return `M ${x1},${y1} H ${mid - sx * R} Q ${mid},${y1} ${mid},${y1 + sy * R} V ${y2 - sy * R} Q ${mid},${y2} ${mid + sx * R},${y2} H ${x2}`;
}

type Tone = 'muted' | 'accent';
function Arrow({d, tone = 'muted', dashed, id, label, lx, ly}: {d: string; tone?: Tone; dashed?: boolean; id: string; label?: string; lx?: number; ly?: number}) {
  const stroke = tone === 'accent' ? C.accent : C.muted;
  const lw = label ? textW(label, 5.4, 8.6) : 0;
  return <g>
    <path d={d} fill="none" stroke={stroke} strokeWidth={dashed ? 1 : 1.2} strokeDasharray={dashed ? '4,3' : undefined} markerEnd={`url(#${id}-${tone})`}/>
    {label && lx !== undefined && ly !== undefined && <>
      <rect x={lx - lw / 2 - 4} y={ly - 7} width={lw + 8} height={12} rx={2} fill={C.paper}/>
      <text x={lx} y={ly + 2} fontFamily={MONO} fontSize={8} letterSpacing="0.06em" fill={stroke} textAnchor="middle">{label}</text>
    </>}
  </g>;
}

function Defs({id}: {id: string}) {
  return <defs>
    {(['muted', 'accent'] as const).map(t => <marker key={t} id={`${id}-${t}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 1,1 L 9,5 L 1,9 z" fill={t === 'accent' ? C.accent : C.muted}/></marker>)}
  </defs>;
}

type LegendKind = Kind | 'arrow' | 'arrow-dashed' | 'arrow-accent';
function Legend({y, w, items}: {y: number; w: number; items: {kind: LegendKind; label: string}[]}) {
  let x = 16;
  return <g>
    <line x1={0} y1={y - 14} x2={w} y2={y - 14} stroke={C.rule} strokeWidth={1}/>
    {items.map(it => {
      const el = <g key={it.label} transform={`translate(${x}, ${y})`}>
        {it.kind.startsWith('arrow')
          ? <line x1={0} y1={6} x2={22} y2={6} stroke={it.kind === 'arrow-accent' ? C.accent : C.muted} strokeWidth={1.2} strokeDasharray={it.kind === 'arrow-dashed' ? '4,3' : undefined}/>
          : <rect x={0} y={0} width={22} height={12} rx={3} fill={FILL[it.kind as Kind].fill} stroke={FILL[it.kind as Kind].stroke} strokeDasharray={FILL[it.kind as Kind].dash} strokeWidth={1}/>}
        <text x={28} y={10} fontFamily={MONO} fontSize={8} fill={C.soft} letterSpacing="0.04em">{it.label}</text>
      </g>;
      x += 40 + textW(it.label, 5.4, 8.4);
      return el;
    })}
  </g>;
}

function Figure({id, w, h, title, desc, caption, children}: {id: string; w: number; h: number; title: string; desc: string; caption: ReactNode; children: ReactNode}) {
  return <figure className="dg-figure">
    <div className="dg-scroll">
      <svg role="img" aria-labelledby={`${id}-title ${id}-desc`} viewBox={`0 0 ${w} ${h}`} style={{width: '100%', minWidth: w, height: 'auto', display: 'block'}}>
        <title id={`${id}-title`}>{title}</title>
        <desc id={`${id}-desc`}>{desc}</desc>
        <Defs id={id}/>
        <rect x={0} y={0} width={w} height={h} fill={C.paper}/>
        {children}
      </svg>
    </div>
    <figcaption className="dg-caption">{caption}</figcaption>
  </figure>;
}

/* ---------------------------------------------------------------- the figures */

/** Oct 4–5: the v2 multi-agent pipeline on the hand-built paper cases. */
export function FigurePipelineV2() {
  const {L} = useLang();
  const id = 'dg-v2';
  const W = 116, X = [24, 160, 296, 432, 568], Y1 = 52, Y2 = 148;
  return <Figure id={id} w={760} h={330} title={L('The v2 multi-agent pipeline', 'v2 多 agent pipeline')} caption={L(
    <>Figure 1. The v2 pipeline of October 5: six LLM roles around one executor that is plain code. Numbers come only from the executor’s logs; the Result Reviewer runs once, after one pilot run per claim; the Debugger gets at most four sessions; the Discrepancy Analyst may hand runs back once for setup errors.</>,
    <>图 1. 10 月 5 日的 v2 pipeline：六个 LLM 角色围绕一个纯代码实现的 executor。数字只来自 executor 的日志；Result Reviewer 只运行一次，在每条 claim 各完成一次 pilot 运行之后；Debugger 最多有四次 session；Discrepancy Analyst 可以因环境配置错误把运行退回一次。</>)}
    desc={L('Paper Analyst, Env Agent and Planner feed the Executor; the Debugger loops with it; the Result Reviewer and the Discrepancy Analyst read its logs; the Evaluator grades against hidden ground truth.',
      'Paper Analyst、Env Agent 和 Planner 依次把结果交给 Executor；Debugger 与它循环交互；Result Reviewer 和 Discrepancy Analyst 读取它的日志；Evaluator 对照隐藏的真值评分。')}>
    <Zone x={16} y={28} w={400} h={88} label={L('READ AND PLAN · LLM ROLES', '阅读与规划 · LLM 角色')}/>
    <Zone x={424} y={28} w={320} h={280} label={L('RUN · THE EXECUTOR IS CODE, NOT AN LLM', '运行 · EXECUTOR 是代码，不是 LLM')}/>
    <Arrow id={id} d={elbow(X[0] + W, Y1 + 24, X[1], Y1 + 24)}/>
    <Arrow id={id} d={elbow(X[1] + W, Y1 + 24, X[2], Y1 + 24)}/>
    <Arrow id={id} d={elbow(X[2] + W, Y1 + 24, X[3], Y1 + 24)} tone="accent"/>
    <Arrow id={id} d={elbow(X[3] + W, Y1 + 16, X[4], Y1 + 16)} tone="accent"/>
    <Arrow id={id} d={elbow(X[4], Y1 + 36, X[3] + W, Y1 + 36)} dashed/>
    <Arrow id={id} d={elbow(X[3] + 44, Y1 + 48, X[3] + 44, Y2)} dashed label={L('FAILED RUN', '运行失败')} lx={X[3] + 14} ly={Y1 + 72}/>
    <Arrow id={id} d={elbow(X[3] + 72, Y2, X[3] + 72, Y1 + 48)} dashed label={L('RETRY ×4', '重试 ×4')} lx={X[3] + 104} ly={Y1 + 72}/>
    <Arrow id={id} d={elbow(X[4] + 58, Y1 + 48, X[4] + 58, Y2)} label={L('ALL LOGS', '全部日志')} lx={X[4] + 96} ly={Y1 + 72}/>
    <Arrow id={id} d={elbow(X[4] + 58, Y2 + 48, X[4] + 58, 240)}/>
    <Node x={X[0]} y={Y1} w={W} tag="read" name="Paper Analyst" sub="PaperSpec" kind="input"/>
    <Node x={X[1]} y={Y1} w={W} tag="shell" name="Env Agent" sub="EnvReport"/>
    <Node x={X[2]} y={Y1} w={W} tag="read" name="Planner" sub={L('claim × seed → run', 'claim × seed → 运行')}/>
    <Node x={X[3]} y={Y1} w={W} tag="code" name="Executor" sub={L('parses the logs', '解析日志')} kind="focal"/>
    <Node x={X[4]} y={Y1} w={W} tag="llm" name="Reviewer" sub={L('once, after pilots', 'pilot 之后审一次')}/>
    <Node x={X[3]} y={Y2} w={W} tag="llm" name="Debugger" sub={L('≤ 4 sessions', '≤ 4 次 session')} kind="optional"/>
    <Node x={X[4]} y={Y2} w={W} tag="llm" name={L('Diagnosis', '诊断')} sub={L('why a claim failed', 'claim 为何失败')}/>
    <Node x={X[4]} y={240} w={W} tag="code" name="Evaluator" sub={L('hidden truth', '隐藏的真值')} kind="store"/>
    <Legend y={312} w={760} items={[{kind: 'focal', label: L('focal', '焦点')}, {kind: 'step', label: L('LLM role', 'LLM 角色')}, {kind: 'optional', label: L('on demand', '按需启动')}, {kind: 'store', label: L('grader', '评分器')}, {kind: 'arrow-accent', label: L('the only path for numbers', '数字的唯一通路')}, {kind: 'arrow-dashed', label: L('retry / return', '重试 / 退回')}]}/>
  </Figure>;
}

/** Oct 16–17: how one answer is graded: tolerance against the re-runs, then where the value came from. */
export function FigureGrading() {
  const {L} = useLang();
  const id = 'dg-grade';
  return <Figure id={id} w={760} h={258} title={L('How an answer is graded', '一个答案如何评分')} caption={L(
    <>Figure 2. Grading on CORE-Bench. An answer must fall inside the tolerance built from three manual re-runs, and it must have been produced by this run: in a command’s log, in a file the run made or changed, or (since November 1) in a figure the agent looked at. Only both together make a task full; a tolerance miss is partial or fail, a provenance miss is partial.</>,
    <>图 2. CORE-Bench 上的评分。答案必须落在由三次人工重跑构建的容差之内，并且必须由本次运行产出：出现在某条命令的日志里、本次运行生成或修改过的文件里，或者（自 11 月 1 日起）agent 查看过的图里。两项同时满足，任务才算 full；容差不满足判为 partial 或 fail，来源不满足判为 partial。</>)}
    desc={L("The agent's answer and the three manual re-runs enter the tolerance check; the run's logs, files and viewed figures enter the provenance check; both must pass for a full verdict.",
      'agent 的答案和三次人工重跑进入容差检查；本次运行的日志、文件和查看过的图进入来源检查；两项都通过才判为 full。')}>
    <Arrow id={id} d={elbow(152, 60, 232, 60)}/>
    <Arrow id={id} d={elbow(152, 140, 232, 76)}/>
    <Arrow id={id} d={elbow(380, 60, 440, 60)} label={L('WITHIN h', '在 h 内')} lx={410} ly={46}/>
    <Arrow id={id} d={`M 88,84 V 96 Q 88,104 96,104 H 184 a 8,8 0 0,1 16,0 H 478 Q 486,104 486,96 V 84`} tone="accent" label={L('EVIDENCE', '证据')} lx={300} ly={118}/>
    <Arrow id={id} d={elbow(604, 60, 644, 100)} tone="accent"/>
    <Arrow id={id} d={elbow(504, 84, 504, 160)} dashed label={L('ONE FAILS', '任一未通过')} lx={548} ly={122}/>
    <Node x={24} y={36} tag="agent" name={L('Answer', '答案')} sub={L('value + cited evidence', '数值 + 引用的证据')} kind="input"/>
    <Node x={24} y={116} tag="truth" name={L('Re-runs ×3', '人工重跑 ×3')} sub={L('mean · s · last digit', '均值 · s · 末位')} kind="store"/>
    <Node x={232} y={36} w={148} tag="rule" name={L('Tolerance', '容差')} sub={L('PI · ½ digit · 1e-5 rel', 'PI · ½ 末位 · 1e-5 相对')}/>
    <Node x={440} y={36} w={164} tag="rule" name={L('Produced here?', '本次运行产出？')} sub={L('logs · new files · figures', '日志 · 新文件 · 图')} kind="focal"/>
    <Node x={440} y={160} w={128} tag="verdict" name="partial / fail" sub={L('or unscored', '或不计分')} kind="optional"/>
    <Node x={644} y={76} w={100} tag="verdict" name="full" sub={L('counts as passed', '算作通过')} kind="store"/>
    <Legend y={240} w={760} items={[{kind: 'focal', label: L('the check that stops shortcuts', '杜绝捷径的检查')}, {kind: 'input', label: L('from the run', '来自本次运行')}, {kind: 'store', label: L('hidden from agents', '对 agent 隐藏')}, {kind: 'arrow-accent', label: L('passes', '通过')}, {kind: 'arrow-dashed', label: L('fails', '未通过')}]}/>
  </Figure>;
}

/** Oct 17–18: the three workflows that are compared, one lane each. */
export function FigureWorkflows() {
  const {L} = useLang();
  const id = 'dg-abd';
  const A = 28, B = 124, D = 220;
  return <Figure id={id} w={760} h={392} title={L('The three workflows: A, B and D', '三种 workflow：A、B 和 D')} caption={L(
    <>Figure 3. A is one ReAct agent with every tool: the baseline. B is the pipeline of Figure 1 fitted to a capsule, routed by code. D keeps a single Planner over a deterministic runtime that runs commands, starts a fresh worker for every setup or debugging task, checks each run with three gates, and alone may end the run.</>,
    <>图 3. A 是一个拥有全部工具的 ReAct agent，作为 baseline。B 是把图 1 的 pipeline 适配到 capsule 上，由代码负责路由。D 只保留一个 Planner，下面是一个确定性的 runtime：它执行命令，为每个环境配置或调试任务启动一个全新的 worker，用三道 gate 检查每次运行，并且只有它能结束运行。</>)}
    desc={L('Three lanes. A: one agent with tools and a workspace. B: Environment Engineer, Planner, Executor with a Debugger loop, Answerer. D: a Planner exchanging patches and wakes with the Runtime, which starts run tasks and workers.',
      '三条泳道。A：一个带工具和 workspace 的 agent。B：Environment Engineer、Planner、带 Debugger 循环的 Executor、Answerer。D：Planner 与 Runtime 之间互相传递 patch 和唤醒，Runtime 负责启动运行任务和 worker。')}>
    <Zone x={16} y={A} w={728} h={80} label={L('A · SINGLE AGENT (BASELINE)', 'A · 单 AGENT（BASELINE）')}/>
    <Zone x={16} y={B} w={728} h={80} label={L('B · FIXED PIPELINE · ROUTING WRITTEN IN CODE', 'B · 固定 PIPELINE · 路由写死在代码里')}/>
    <Zone x={16} y={D} w={728} h={136} label="D · PLANNER + RUNTIME + WORKERS"/>
    <Arrow id={id} d={elbow(256, A + 48, 336, A + 48)} label={L('ALL TOOLS', '全部工具')} lx={296} ly={A + 34}/>
    <Node x={88} y={A + 24} w={168} tag="llm" name={L('One agent', '单个 agent')} sub="read · write · shell · view"/>
    <Node x={336} y={A + 24} w={160} tag="sandbox" name="Workspace" sub={L('submits answers itself', '自己提交答案')} kind="store"/>
    <Arrow id={id} d={elbow(216, B + 48, 232, B + 48)}/>
    <Arrow id={id} d={elbow(360, B + 48, 376, B + 48)}/>
    <Arrow id={id} d={elbow(504, B + 40, 520, B + 40)} dashed/>
    <Arrow id={id} d={elbow(520, B + 56, 504, B + 56)} dashed/>
    <Arrow id={id} d={elbow(592, B + 48, 616, B + 48)}/>
    <Node x={88} y={B + 24} tag="llm" name="Env Engineer" sub={L('installs, finds entry', '装环境、找入口')}/>
    <Node x={232} y={B + 24} tag="llm" name="Planner" sub={L('command per question', '每道题一条命令')}/>
    <Node x={376} y={B + 24} tag="code" name="Executor" sub={L('logs', '日志')} kind="focal"/>
    <Node x={520} y={B + 24} w={72} tag="llm" name="Debug" sub="≤ 4" kind="optional"/>
    <Node x={616} y={B + 24} w={128} tag="llm" name="Answerer" sub={L('reads logs and figures', '读日志和图')}/>
    <Arrow id={id} d={elbow(216, D + 40, 296, D + 40)} tone="accent" label="PATCH" lx={256} ly={D + 26}/>
    <Arrow id={id} d={elbow(296, D + 64, 216, D + 64)} dashed label={L('WAKE', '唤醒')} lx={256} ly={D + 80}/>
    <Arrow id={id} d={elbow(424, D + 52, 464, D + 52)} label={L('RUN', '运行')} lx={444} ly={D + 38}/>
    <Arrow id={id} d={`M 360,${D + 76} V ${D + 96} Q 360,${D + 104} 368,${D + 104} H 464`} label={L('DELEGATE', '委派')} lx={412} ly={D + 118}/>
    <Arrow id={id} d={`M 464,${D + 92} H 388 Q 380,${D + 92} 380,${D + 84} V ${D + 76}`} dashed label={L('REPORT', '报告')} lx={422} ly={D + 80}/>
    <Node x={88} y={D + 28} tag="llm" name="Planner" sub={L('the only planner', '唯一的 planner')}/>
    <Node x={296} y={D + 28} tag="code" name="Runtime" sub={L('gates · ends the run', 'gates · 结束运行')} kind="focal"/>
    <Node x={464} y={D + 28} w={120} tag="shell" name={L('Run task', '运行任务')} sub={L('smoke, then full', '先 smoke，再全量')} kind="store"/>
    <Node x={464} y={D + 80} w={120} tag="llm" name="Worker" sub={L('fresh context', '全新上下文')} kind="optional"/>
    <Legend y={374} w={760} items={[{kind: 'focal', label: L('code that owns the numbers', '掌管数字的代码')}, {kind: 'step', label: L('LLM role', 'LLM 角色')}, {kind: 'optional', label: L('started on demand', '按需启动')}, {kind: 'store', label: L('commands / files', '命令 / 文件')}, {kind: 'arrow-dashed', label: L('back channel', '回传通道')}]}/>
  </Figure>;
}

/** D's loop in detail: what the runtime does between two Planner turns. */
export function FigurePlannerLoop() {
  const {L} = useLang();
  const id = 'dg-loop';
  return <Figure id={id} w={760} h={288} title={L('D: one turn of the Planner–Runtime loop', 'D：Planner–Runtime 循环的一轮')} caption={L(
    <>Figure 4. One turn of D. The Planner submits a patch: tasks to add, cancel or replace, ledger notes, or a finish proposal. The runtime applies it atomically or sends the problems back; a run passes a plan check, a smoke run and an evidence check; an agent task goes to a fresh worker that sees only its delegation and returns a structured report. The Planner is woken with what changed and computed progress; three stalls reset its conversation from the ledger; only the runtime, through its finish gate, ends the run.</>,
    <>图 4. D 的一轮。Planner 提交一个 patch：要添加、取消或替换的任务，ledger 记录，或者一个结束提议。runtime 以原子方式应用它，或者把问题退回；一次运行要依次通过计划检查、smoke run 和证据检查；agent 任务交给一个全新的 worker，它只看得到自己的委派，并返回一份结构化报告。Planner 被唤醒时会收到发生了哪些变化，以及计算好的进度；连续三次停滞会根据 ledger 重置它的对话；只有 runtime 能通过它的 finish gate 结束运行。</>)}
    desc={L("The Planner sends an ExperimentPatch to the Runtime. The Runtime validates it, runs ready tasks through three gates to a full run, delegates agent tasks to a worker, and wakes the Planner with the changes. The full run's evidence lets the run end.",
      'Planner 向 Runtime 发送 ExperimentPatch。Runtime 校验它，让就绪的任务经过三道 gate 进入完整运行，把 agent 任务委派给 worker，并带着这些变化唤醒 Planner。完整运行留下的证据让整个运行得以结束。')}>
    <Arrow id={id} d={elbow(164, 58, 280, 58)} tone="accent" label="PATCH" lx={222} ly={44}/>
    <Arrow id={id} d={elbow(280, 78, 164, 78)} dashed label={L('PROBLEMS', '问题')} lx={222} ly={94}/>
    <Arrow id={id} d={elbow(344, 92, 344, 156)} label={L('RUN TASK', '运行任务')} lx={392} ly={124}/>
    <Arrow id={id} d={elbow(408, 64, 520, 64)} label={L('AGENT TASK', 'AGENT 任务')} lx={464} ly={50}/>
    <Arrow id={id} d={elbow(520, 88, 408, 88)} dashed label={L('REPORT', '报告')} lx={464} ly={104}/>
    <Arrow id={id} d={`M 300,92 V 124 Q 300,132 292,132 H 96 Q 88,132 88,124 V 92`} dashed label={L('WAKE', '唤醒')} lx={194} ly={118}/>
    <Arrow id={id} d={elbow(472, 180, 520, 180)}/>
    <Arrow id={id} d={elbow(632, 180, 680, 180)} tone="accent" label={L('PASS', '通过')} lx={656} ly={166}/>
    <Node x={24} y={44} w={140} tag="llm" name="Planner" sub={L('ledger · plan · finish?', 'ledger · 计划 · 结束？')}/>
    <Node x={280} y={44} tag="code" name="Runtime" sub={L('applies the patch', '应用 patch')} kind="focal"/>
    <Node x={520} y={44} w={148} tag="llm" name="Worker" sub={L('setup · debug · diagnose', '配置 · 调试 · 诊断')} kind="optional"/>
    <Node x={280} y={156} w={192} tag="gates" name={L('Plan · smoke · evidence', '计划 · smoke · 证据')} sub={L('deterministic checks', '确定性检查')} kind="store"/>
    <Node x={520} y={156} w={112} tag="shell" name={L('Full run', '完整运行')} sub={L('log = evidence', '日志即证据')} kind="store"/>
    <Node x={680} y={156} w={64} tag="end" name={L('Done', '完成')} sub={L('gate ok', 'gate 通过')} kind="input"/>
    <Legend y={270} w={760} items={[{kind: 'focal', label: L('source of truth', '事实来源')}, {kind: 'store', label: L('checks and runs', '检查与运行')}, {kind: 'optional', label: L('fresh worker', '全新 worker')}, {kind: 'arrow-accent', label: 'planner → runtime'}, {kind: 'arrow-dashed', label: 'runtime → planner'}]}/>
  </Figure>;
}

/** The workflow comparison across the rounds: full-task rates, A / B / D side by side. */
export function FigureComparison() {
  const {L} = useLang();
  const id = 'dg-bars';
  const groups: {label: string; sub: string; vals: [number, number, number]; n: number}[] = [
    {label: L('Dev round 1', 'Dev 第 1 轮'), sub: L('20 Python tasks · v2', '20 个 Python 任务 · v2'), vals: [13, 12, 13], n: 17},
    {label: L('Dev round 2', 'Dev 第 2 轮'), sub: L('45 tasks · v4', '45 个任务 · v4'), vals: [32, 34, 34], n: 42},
    {label: L('Dev round 3', 'Dev 第 3 轮'), sub: 'Haiku · v5', vals: [32, 33, 35], n: 42},
    {label: L('Dev round 3', 'Dev 第 3 轮'), sub: 'Sonnet · v5', vals: [31, 33, 36], n: 42},
    {label: L('Dev round 3', 'Dev 第 3 轮'), sub: L('Haiku · no skills', 'Haiku · 无 skill'), vals: [31, 33, 31], n: 42},
    {label: L('Test split', 'Test split'), sub: L('30 tasks · frozen v5', '30 个任务 · 冻结的 v5'), vals: [29, 28, 26], n: 30},
  ];
  const x0 = 56, y0 = 40, plotH = 150, groupW = 112, barW = 24, gap = 4;
  const series = [{name: L('A · single agent', 'A · 单 agent'), fill: C.muted}, {name: L('B · fixed pipeline', 'B · 固定 pipeline'), fill: C.ink}, {name: 'D · planner + workers', fill: C.accent}];
  return <Figure id={id} w={760} h={286} title={L('Workflows A, B and D across the rounds', '各轮中的 workflow A、B、D')} caption={L(
    <>Figure 5. Share of scored tasks whose every question was answered within tolerance and produced by the run. The dev rounds tuned the skill library; the test split ran once with it frozen. No round separates the three workflows beyond noise: every paired McNemar p is 0.125 or more.</>,
    <>图 5. 已计分任务中，每道题都在容差之内、且由本次运行产出的任务所占的比例。dev 各轮用来调优 skill 库；test split 在 skill 库冻结后只跑了一次。没有哪一轮能在噪声之外区分三种 workflow：每个配对 McNemar 检验的 p 值都不低于 0.125。</>)}
    desc={L('Grouped bars: for six rounds, the pass rate of workflows A, B and D. They stay within a few points of each other in every round; D leads slightly on dev round 3 and trails on the test split.',
      '分组柱状图：六轮中 workflow A、B、D 各自的通过率。每一轮它们都只相差几个百分点；D 在 dev 第 3 轮略微领先，在 test split 上落后。')}>
    {[0, 25, 50, 75, 100].map(t => <g key={t}>
      <line x1={x0} y1={y0 + plotH - plotH * t / 100} x2={x0 + groups.length * groupW} y2={y0 + plotH - plotH * t / 100} stroke={C.rule} strokeWidth={1}/>
      <text x={x0 - 8} y={y0 + plotH - plotH * t / 100 + 3} fontFamily={MONO} fontSize={8} fill={C.soft} textAnchor="end">{t}%</text>
    </g>)}
    {groups.map((g, gi) => <g key={gi}>
      {g.vals.map((v, si) => {
        const h = plotH * (v / g.n), x = x0 + gi * groupW + 14 + si * (barW + gap);
        return <g key={si}>
          <rect x={x} y={y0 + plotH - h} width={barW} height={h} rx={2} fill={series[si].fill} opacity={si === 2 ? 1 : 0.85}><title>{`${series[si].name}: ${v} / ${g.n}`}</title></rect>
        </g>;
      })}
      <text x={x0 + gi * groupW + groupW / 2} y={y0 + plotH + 16} fontFamily={SANS} fontSize={10.5} fontWeight={600} fill={C.ink} textAnchor="middle">{g.label}</text>
      <text x={x0 + gi * groupW + groupW / 2} y={y0 + plotH + 28} fontFamily={MONO} fontSize={8} fill={C.soft} textAnchor="middle">{g.sub}</text>
    </g>)}
    <text x={x0} y={24} fontFamily={MONO} fontSize={8} letterSpacing="0.14em" fill={C.soft}>{L('FULL TASKS / SCORED TASKS', 'FULL 任务数 / 计分任务数')}</text>
    <g transform={`translate(${x0}, ${y0 + plotH + 48})`}>
      {series.map((s, i) => <g key={s.name} transform={`translate(${i * 160}, 0)`}>
        <rect x={0} y={0} width={14} height={10} rx={2} fill={s.fill}/>
        <text x={20} y={9} fontFamily={MONO} fontSize={8.5} fill={C.soft}>{s.name}</text>
      </g>)}
    </g>
  </Figure>;
}
