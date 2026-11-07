// Diagrams for the changelog, drawn by the rules of the diagram-design skill (github.com/cathrynlavery/diagram-design):
// inline SVG in its default editorial skin (paper / ink / muted / one accent), node boxes at rx=6 with a rectangular
// type tag, orthogonal connectors with r=8 elbows and masked labels, arrows drawn before boxes, a legend strip at the
// bottom, at most 9 nodes and 1–2 accented elements per figure. Colors are CSS variables (app.css, --dg-*) so the
// dark skin applies under .dark.
import type {ReactNode} from 'react';

const R = 8;
const C = {paper: 'var(--dg-paper)', paper2: 'var(--dg-paper-2)', ink: 'var(--dg-ink)', muted: 'var(--dg-muted)', soft: 'var(--dg-soft)',
  rule: 'var(--dg-rule)', accent: 'var(--dg-accent)', accentTint: 'var(--dg-accent-tint)', link: 'var(--dg-link)'};
const SANS = 'Geist, system-ui, sans-serif';
const MONO = '"Geist Mono", ui-monospace, monospace';

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
    <rect x={x + 10} y={y + 4} width={label.length * 5.4 + 10} height={12} rx={2} fill={C.paper}/>
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
  return <g>
    <path d={d} fill="none" stroke={stroke} strokeWidth={dashed ? 1 : 1.2} strokeDasharray={dashed ? '4,3' : undefined} markerEnd={`url(#${id}-${tone})`}/>
    {label && lx !== undefined && ly !== undefined && <>
      <rect x={lx - label.length * 2.7 - 4} y={ly - 7} width={label.length * 5.4 + 8} height={12} rx={2} fill={C.paper}/>
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
      x += 40 + it.label.length * 5.4;
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
  const id = 'dg-v2';
  const W = 116, X = [24, 160, 296, 432, 568], Y1 = 52, Y2 = 148;
  return <Figure id={id} w={760} h={330} title="The v2 multi-agent pipeline" caption={<>Figure 1. The v2 pipeline of October 5: six LLM roles around one executor that is plain code. Numbers come only from the executor’s logs; the Result Reviewer runs once, after one pilot run per claim; the Debugger gets at most four sessions; the Discrepancy Analyst may hand runs back once for setup errors.</>}
    desc="Paper Analyst, Env Agent and Planner feed the Executor; the Debugger loops with it; the Result Reviewer and the Discrepancy Analyst read its logs; the Evaluator grades against hidden ground truth.">
    <Zone x={16} y={28} w={400} h={88} label="READ AND PLAN · LLM ROLES"/>
    <Zone x={424} y={28} w={320} h={280} label="RUN · THE EXECUTOR IS CODE, NOT AN LLM"/>
    <Arrow id={id} d={elbow(X[0] + W, Y1 + 24, X[1], Y1 + 24)}/>
    <Arrow id={id} d={elbow(X[1] + W, Y1 + 24, X[2], Y1 + 24)}/>
    <Arrow id={id} d={elbow(X[2] + W, Y1 + 24, X[3], Y1 + 24)} tone="accent"/>
    <Arrow id={id} d={elbow(X[3] + W, Y1 + 16, X[4], Y1 + 16)} tone="accent"/>
    <Arrow id={id} d={elbow(X[4], Y1 + 36, X[3] + W, Y1 + 36)} dashed/>
    <Arrow id={id} d={elbow(X[3] + 44, Y1 + 48, X[3] + 44, Y2)} dashed label="FAILED RUN" lx={X[3] + 14} ly={Y1 + 72}/>
    <Arrow id={id} d={elbow(X[3] + 72, Y2, X[3] + 72, Y1 + 48)} dashed label="RETRY ×4" lx={X[3] + 104} ly={Y1 + 72}/>
    <Arrow id={id} d={elbow(X[4] + 58, Y1 + 48, X[4] + 58, Y2)} label="ALL LOGS" lx={X[4] + 96} ly={Y1 + 72}/>
    <Arrow id={id} d={elbow(X[4] + 58, Y2 + 48, X[4] + 58, 240)}/>
    <Node x={X[0]} y={Y1} w={W} tag="read" name="Paper Analyst" sub="PaperSpec" kind="input"/>
    <Node x={X[1]} y={Y1} w={W} tag="shell" name="Env Agent" sub="EnvReport"/>
    <Node x={X[2]} y={Y1} w={W} tag="read" name="Planner" sub="claim × seed → run"/>
    <Node x={X[3]} y={Y1} w={W} tag="code" name="Executor" sub="parses the logs" kind="focal"/>
    <Node x={X[4]} y={Y1} w={W} tag="llm" name="Reviewer" sub="once, after pilots"/>
    <Node x={X[3]} y={Y2} w={W} tag="llm" name="Debugger" sub="≤ 4 sessions" kind="optional"/>
    <Node x={X[4]} y={Y2} w={W} tag="llm" name="Diagnosis" sub="why a claim failed"/>
    <Node x={X[4]} y={240} w={W} tag="code" name="Evaluator" sub="hidden truth" kind="store"/>
    <Legend y={312} w={760} items={[{kind: 'focal', label: 'focal'}, {kind: 'step', label: 'LLM role'}, {kind: 'optional', label: 'on demand'}, {kind: 'store', label: 'grader'}, {kind: 'arrow-accent', label: 'the only path for numbers'}, {kind: 'arrow-dashed', label: 'retry / return'}]}/>
  </Figure>;
}

/** Oct 16–17: how one answer is graded: tolerance against the re-runs, then where the value came from. */
export function FigureGrading() {
  const id = 'dg-grade';
  return <Figure id={id} w={760} h={258} title="How an answer is graded" caption={<>Figure 2. Grading on CORE-Bench. An answer must fall inside the tolerance built from three manual re-runs, and it must have been produced by this run: in a command’s log, in a file the run made or changed, or (since November 1) in a figure the agent looked at. Only both together make a task full; a tolerance miss is partial or fail, a provenance miss is partial.</>}
    desc="The agent's answer and the three manual re-runs enter the tolerance check; the run's logs, files and viewed figures enter the provenance check; both must pass for a full verdict.">
    <Arrow id={id} d={elbow(152, 60, 232, 60)}/>
    <Arrow id={id} d={elbow(152, 140, 232, 76)}/>
    <Arrow id={id} d={elbow(380, 60, 440, 60)} label="WITHIN h" lx={410} ly={46}/>
    <Arrow id={id} d={`M 88,84 V 96 Q 88,104 96,104 H 184 a 8,8 0 0,1 16,0 H 478 Q 486,104 486,96 V 84`} tone="accent" label="EVIDENCE" lx={300} ly={118}/>
    <Arrow id={id} d={elbow(604, 60, 644, 100)} tone="accent"/>
    <Arrow id={id} d={elbow(504, 84, 504, 160)} dashed label="ONE FAILS" lx={548} ly={122}/>
    <Node x={24} y={36} tag="agent" name="Answer" sub="value + cited evidence" kind="input"/>
    <Node x={24} y={116} tag="truth" name="Re-runs ×3" sub="mean · s · last digit" kind="store"/>
    <Node x={232} y={36} w={148} tag="rule" name="Tolerance" sub="PI · ½ digit · 1e-5 rel"/>
    <Node x={440} y={36} w={164} tag="rule" name="Produced here?" sub="logs · new files · figures" kind="focal"/>
    <Node x={440} y={160} w={128} tag="verdict" name="partial / fail" sub="or unscored" kind="optional"/>
    <Node x={644} y={76} w={100} tag="verdict" name="full" sub="counts as passed" kind="store"/>
    <Legend y={240} w={760} items={[{kind: 'focal', label: 'the check that stops shortcuts'}, {kind: 'input', label: 'from the run'}, {kind: 'store', label: 'hidden from agents'}, {kind: 'arrow-accent', label: 'passes'}, {kind: 'arrow-dashed', label: 'fails'}]}/>
  </Figure>;
}

/** Oct 17–18: the three workflows that are compared, one lane each. */
export function FigureWorkflows() {
  const id = 'dg-abd';
  const A = 28, B = 124, D = 220;
  return <Figure id={id} w={760} h={392} title="The three workflows: A, B and D" caption={<>Figure 3. A is one ReAct agent with every tool: the baseline. B is the pipeline of Figure 1 fitted to a capsule, routed by code. D keeps a single Planner over a deterministic runtime that runs commands, starts a fresh worker for every setup or debugging task, checks each run with three gates, and alone may end the run.</>}
    desc="Three lanes. A: one agent with tools and a workspace. B: Environment Engineer, Planner, Executor with a Debugger loop, Answerer. D: a Planner exchanging patches and wakes with the Runtime, which starts run tasks and workers.">
    <Zone x={16} y={A} w={728} h={80} label="A · SINGLE AGENT (BASELINE)"/>
    <Zone x={16} y={B} w={728} h={80} label="B · FIXED PIPELINE · ROUTING WRITTEN IN CODE"/>
    <Zone x={16} y={D} w={728} h={136} label="D · PLANNER + RUNTIME + WORKERS"/>
    <Arrow id={id} d={elbow(256, A + 48, 336, A + 48)} label="ALL TOOLS" lx={296} ly={A + 34}/>
    <Node x={88} y={A + 24} w={168} tag="llm" name="One agent" sub="read · write · shell · view"/>
    <Node x={336} y={A + 24} w={160} tag="sandbox" name="Workspace" sub="submits answers itself" kind="store"/>
    <Arrow id={id} d={elbow(216, B + 48, 232, B + 48)}/>
    <Arrow id={id} d={elbow(360, B + 48, 376, B + 48)}/>
    <Arrow id={id} d={elbow(504, B + 40, 520, B + 40)} dashed/>
    <Arrow id={id} d={elbow(520, B + 56, 504, B + 56)} dashed/>
    <Arrow id={id} d={elbow(592, B + 48, 616, B + 48)}/>
    <Node x={88} y={B + 24} tag="llm" name="Env Engineer" sub="installs, finds entry"/>
    <Node x={232} y={B + 24} tag="llm" name="Planner" sub="command per question"/>
    <Node x={376} y={B + 24} tag="code" name="Executor" sub="logs" kind="focal"/>
    <Node x={520} y={B + 24} w={72} tag="llm" name="Debug" sub="≤ 4" kind="optional"/>
    <Node x={616} y={B + 24} w={128} tag="llm" name="Answerer" sub="reads logs and figures"/>
    <Arrow id={id} d={elbow(216, D + 40, 296, D + 40)} tone="accent" label="PATCH" lx={256} ly={D + 26}/>
    <Arrow id={id} d={elbow(296, D + 64, 216, D + 64)} dashed label="WAKE" lx={256} ly={D + 80}/>
    <Arrow id={id} d={elbow(424, D + 52, 464, D + 52)} label="RUN" lx={444} ly={D + 38}/>
    <Arrow id={id} d={`M 360,${D + 76} V ${D + 96} Q 360,${D + 104} 368,${D + 104} H 464`} label="DELEGATE" lx={412} ly={D + 118}/>
    <Arrow id={id} d={`M 464,${D + 92} H 388 Q 380,${D + 92} 380,${D + 84} V ${D + 76}`} dashed label="REPORT" lx={422} ly={D + 80}/>
    <Node x={88} y={D + 28} tag="llm" name="Planner" sub="the only planner"/>
    <Node x={296} y={D + 28} tag="code" name="Runtime" sub="gates · ends the run" kind="focal"/>
    <Node x={464} y={D + 28} w={120} tag="shell" name="Run task" sub="smoke, then full" kind="store"/>
    <Node x={464} y={D + 80} w={120} tag="llm" name="Worker" sub="fresh context" kind="optional"/>
    <Legend y={374} w={760} items={[{kind: 'focal', label: 'code that owns the numbers'}, {kind: 'step', label: 'LLM role'}, {kind: 'optional', label: 'started on demand'}, {kind: 'store', label: 'commands / files'}, {kind: 'arrow-dashed', label: 'back channel'}]}/>
  </Figure>;
}

/** D's loop in detail: what the runtime does between two Planner turns. */
export function FigurePlannerLoop() {
  const id = 'dg-loop';
  return <Figure id={id} w={760} h={288} title="D: one turn of the Planner–Runtime loop" caption={<>Figure 4. One turn of D. The Planner submits a patch: tasks to add, cancel or replace, ledger notes, or a finish proposal. The runtime applies it atomically or sends the problems back; a run passes a plan check, a smoke run and an evidence check; an agent task goes to a fresh worker that sees only its delegation and returns a structured report. The Planner is woken with what changed and computed progress; three stalls reset its conversation from the ledger; only the runtime, through its finish gate, ends the run.</>}
    desc="The Planner sends an ExperimentPatch to the Runtime. The Runtime validates it, runs ready tasks through three gates to a full run, delegates agent tasks to a worker, and wakes the Planner with the changes. The full run's evidence lets the run end.">
    <Arrow id={id} d={elbow(164, 58, 280, 58)} tone="accent" label="PATCH" lx={222} ly={44}/>
    <Arrow id={id} d={elbow(280, 78, 164, 78)} dashed label="PROBLEMS" lx={222} ly={94}/>
    <Arrow id={id} d={elbow(344, 92, 344, 156)} label="RUN TASK" lx={392} ly={124}/>
    <Arrow id={id} d={elbow(408, 64, 520, 64)} label="AGENT TASK" lx={464} ly={50}/>
    <Arrow id={id} d={elbow(520, 88, 408, 88)} dashed label="REPORT" lx={464} ly={104}/>
    <Arrow id={id} d={`M 300,92 V 124 Q 300,132 292,132 H 96 Q 88,132 88,124 V 92`} dashed label="WAKE" lx={194} ly={118}/>
    <Arrow id={id} d={elbow(472, 180, 520, 180)}/>
    <Arrow id={id} d={elbow(632, 180, 680, 180)} tone="accent" label="PASS" lx={656} ly={166}/>
    <Node x={24} y={44} w={140} tag="llm" name="Planner" sub="ledger · plan · finish?"/>
    <Node x={280} y={44} tag="code" name="Runtime" sub="applies the patch" kind="focal"/>
    <Node x={520} y={44} w={148} tag="llm" name="Worker" sub="setup · debug · diagnose" kind="optional"/>
    <Node x={280} y={156} w={192} tag="gates" name="Plan · smoke · evidence" sub="deterministic checks" kind="store"/>
    <Node x={520} y={156} w={112} tag="shell" name="Full run" sub="log = evidence" kind="store"/>
    <Node x={680} y={156} w={64} tag="end" name="Done" sub="gate ok" kind="input"/>
    <Legend y={270} w={760} items={[{kind: 'focal', label: 'source of truth'}, {kind: 'store', label: 'checks and runs'}, {kind: 'optional', label: 'fresh worker'}, {kind: 'arrow-accent', label: 'planner → runtime'}, {kind: 'arrow-dashed', label: 'runtime → planner'}]}/>
  </Figure>;
}

/** The workflow comparison across the rounds: full-task rates, A / B / D side by side. */
export function FigureComparison() {
  const id = 'dg-bars';
  const groups: {label: string; sub: string; vals: [number, number, number]; n: number}[] = [
    {label: 'Dev round 1', sub: '20 Python tasks · v2', vals: [13, 12, 13], n: 17},
    {label: 'Dev round 2', sub: '45 tasks · v4', vals: [32, 34, 34], n: 42},
    {label: 'Dev round 3', sub: 'Haiku · v5', vals: [32, 33, 35], n: 42},
    {label: 'Dev round 3', sub: 'Sonnet · v5', vals: [31, 33, 36], n: 42},
    {label: 'Dev round 3', sub: 'Haiku · no skills', vals: [31, 33, 31], n: 42},
    {label: 'Test split', sub: '30 tasks · frozen v5', vals: [29, 28, 26], n: 30},
  ];
  const x0 = 56, y0 = 40, plotH = 150, groupW = 112, barW = 24, gap = 4;
  const series = [{name: 'A · single agent', fill: C.muted}, {name: 'B · fixed pipeline', fill: C.ink}, {name: 'D · planner + workers', fill: C.accent}];
  return <Figure id={id} w={760} h={286} title="Workflows A, B and D across the rounds" caption={<>Figure 5. Share of scored tasks whose every question was answered within tolerance and produced by the run. The dev rounds tuned the skill library; the test split ran once with it frozen. No round separates the three workflows beyond noise: every paired McNemar p is 0.125 or more.</>}
    desc="Grouped bars: for six rounds, the pass rate of workflows A, B and D. They stay within a few points of each other in every round; D leads slightly on dev round 3 and trails on the test split.">
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
    <text x={x0} y={24} fontFamily={MONO} fontSize={8} letterSpacing="0.14em" fill={C.soft}>FULL TASKS / SCORED TASKS</text>
    <g transform={`translate(${x0}, ${y0 + plotH + 48})`}>
      {series.map((s, i) => <g key={s.name} transform={`translate(${i * 160}, 0)`}>
        <rect x={0} y={0} width={14} height={10} rx={2} fill={s.fill}/>
        <text x={20} y={9} fontFamily={MONO} fontSize={8.5} fill={C.soft}>{s.name}</text>
      </g>)}
    </g>
  </Figure>;
}
