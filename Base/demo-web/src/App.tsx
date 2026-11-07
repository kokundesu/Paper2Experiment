// The demo as an agent chat: the user says what to reproduce, the assistant turns it into a task (asking for the GitHub
// address when the message has none), starts the chosen workflow on a yes, and reports in the thread: the run's message
// is a fixed-size window with the live agent graph (scaled to fit) and the selected agent's steps, then a table of the
// results against the paper. The message box (Composer) picks the workflow, the model, the run folder and the example
// tasks; the top bar reopens the user's earlier runs. AI messages carry the model vendor's logo, as in Alex.
import {useCallback, useEffect, useRef, useState, type ReactNode} from 'react';
import {Check, ChevronDown, FlaskConical, Github, History, ListChecks, Loader2, Maximize2, Minimize2, Moon, Package, Play, Square, Sun, X} from 'lucide-react';
import {api} from './api';
import {AgentRun, type RunOutcome} from './agent-run/agent-run';
import {OrchestrationGraph} from './graph/OrchestrationGraph';
import {Avatar, ROLE_ICONS, toolIcon} from './icons';
import {VendorLogo} from './provider-logos';
import {Composer, VENDOR_NAME, WF_LABEL} from './Composer';
import {ChangelogPage} from './Changelog';
import {ProviderGlyph} from './alex/modules/chat/components/ui/model-picker';
import {Loader} from './alex/modules/chat/components/ui/loader';
import {ShiningText} from './alex/modules/chat/components/ui/shining-text';
import type {Answer, Comparison, ExampleTask, GraphNode, HistoryRun, JobState, Options, PaperValues, Spec, Workdir} from './types';

const PROVENANCE: Record<string, string> = {produced: 'Produced by this run', typed: 'Only in text the agent wrote itself',
  preexisting_only: 'Only in files shipped with the code', not_found: 'Not found in the run’s output'};
const IMAGE = /\.(png|jpe?g|gif|svg|webp)$/i;
const FIGURE = /\.(png|jpe?g|gif|svg|webp|pdf)$/i;
const GITHUB = /https?:\/\/(?:www\.)?github\.com\/[\w.-]+\/[\w.-]+/;
const START_WORDS = /^(start|go|yes|ok|okay|run|run it|开始|好|确认)[.!。！]?$/i;

export const SUGGESTIONS = [
  {label: 'KalmanNet, Table I (signal processing, ~5 min)', text: 'Using the official code https://github.com/KalmanNet/KalmanNet_TSP on CPU, reproduce the Test T = 20 row of Table I of the KalmanNet paper: linear 2x2 state-space model (F in canonical form, H = I, full information, nu = 0 dB, 1/r^2 = 20 dB), trained and tested on trajectories of length T = 20. Report the test MSE (dB) of KalmanNet and of the Kalman filter with the true F, H, Q, R.'},
  {label: 'A request without the code’s address', text: 'Reproduce the T = 20 row of Table I of the KalmanNet paper: the test MSE of KalmanNet and of the Kalman filter.'},
];

// every AI message records the vendor of the model that wrote it, for its author line
type Msg =
  | {id: number; role: 'user'; text: string}
  | {id: number; role: 'assistant'; by: string; type: 'thinking'}
  | {id: number; role: 'assistant'; by: string; type: 'text'; text: string}
  | {id: number; role: 'assistant'; by: string; type: 'ask_url'; prompt: string; resolved?: boolean}
  | {id: number; role: 'assistant'; by: string; type: 'spec'; spec: Spec; paper: PaperValues; cost: number; started?: boolean}
  | {id: number; role: 'assistant'; by: string; type: 'run'; key: string};
type NewMsg = Msg extends infer M ? M extends Msg ? Omit<M, 'id' | 'by'> : never : never;

let nextId = 1;
const newId = () => nextId++;

function fromHash(): string | null {
  const m = /job=([\w.-]+)/.exec(window.location.hash);
  return m ? m[1] : null;
}

/** The node and step working right now: the newest running step, else the newest running node. */
function current(nodes: GraphNode[]) {
  let best: {node: GraphNode; step?: GraphNode['steps'][number]; t: number} | null = null;
  for (const n of nodes) for (const s of n.steps)
    if (s.status === 'running' && s.startedAt && (!best || Date.parse(s.startedAt) >= best.t)) best = {node: n, step: s, t: Date.parse(s.startedAt)};
  if (best) return best;
  const live = nodes.filter(n => n.status === 'running');
  return live.length ? {node: live[live.length - 1], t: 0} : null;
}

const isLive = (job: JobState | null) => !!job && (job.phase === 'running' || job.phase === 'preparing');
const minutes = (s: number) => s < 60 ? `${Math.round(s)} s` : `${(s / 60).toFixed(s < 600 ? 1 : 0)} min`;
const ago = (t: number) => { const s = Date.now() / 1000 - t; return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; };

/** A value for display: numbers to 6 significant digits (scientific when tiny or huge), anything else as is. */
function show(v: unknown): string {
  if (typeof v === 'number') {
    const a = Math.abs(v);
    return a !== 0 && (a < 1e-3 || a >= 1e7) ? v.toExponential(2) : String(+v.toPrecision(6));
  }
  return typeof v === 'string' ? v : JSON.stringify(v);
}

/* ---------------------------------------------------------------- menus */

/** A button with a menu under (or above) it; closes on a pick, an outside click or Escape. */
function Menu({label, title, up, wide, children}: {label: ReactNode; title?: string; up?: boolean; wide?: boolean;
  children: (close: () => void) => ReactNode}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  return <div className="menu" ref={ref}>
    <button type="button" className={`menu-trigger${open ? ' is-open' : ''}`} title={title} aria-expanded={open} onClick={() => setOpen(o => !o)}>
      {label}<ChevronDown size={13} className="menu-chevron"/></button>
    {open && <div className={`menu-panel${up ? ' is-up' : ''}${wide ? ' is-wide' : ''}`} role="menu">{children(() => setOpen(false))}</div>}
  </div>;
}

function HistoryMenu({runs, onOpen, onRefresh}: {runs: HistoryRun[] | null; onOpen: (r: HistoryRun) => void; onRefresh: () => void}) {
  return <div onMouseDown={onRefresh}>
    <Menu wide label={<><History size={14}/><span>History</span></>}>
      {close => <>
        <div className="menu-head">Your reproductions, newest first. Open one to see its graph and results again.</div>
        <div className="menu-scroll">
          {!runs ? <div className="menu-empty"><Loader2 size={14} className="spin"/></div>
            : !runs.length ? <div className="menu-empty">Nothing yet: ask for a reproduction or pick an example</div>
            : runs.map(r => <button type="button" key={r.key} role="menuitem" className="menu-item" onClick={() => { close(); onOpen(r); }}>
              <span className={`menu-dot is-${r.status}`} title={r.status}/>
              <span className="menu-main"><b>{r.title}</b>
                <small>{WF_LABEL[r.workflow] ?? r.workflow} · {r.profile}{r.wall_s ? ` · ${minutes(r.wall_s)}` : ''}{r.cost ? ` · $${r.cost.toFixed(3)}` : ''}
                  {r.answered !== null && r.answered !== undefined ? ` · ${r.answered}/${r.questions} answered` : ''}</small></span>
              <span className="menu-meta">{r.status === 'running' ? 'running' : r.started ? ago(r.started) : ''}</span>
            </button>)}
        </div>
      </>}
    </Menu>
  </div>;
}

function TopBar({dark, onTheme, children}: {dark: boolean; onTheme: () => void; children: ReactNode}) {
  return <header className="topbar app-topbar">
    <div className="topbar-left">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M8.5 2.5C8.7 6.1 9.9 7.3 13.5 7.5C9.9 7.7 8.7 8.9 8.5 12.5C8.3 8.9 7.1 7.7 3.5 7.5C7.1 7.3 8.3 6.1 8.5 2.5Z" fill="#2E7CF6"/>
        <path d="M14.5 11.8C14.6 13.2 15.1 13.7 16.5 13.8C15.1 13.9 14.6 14.4 14.5 15.8C14.4 14.4 13.9 13.9 12.5 13.8C13.9 13.7 14.4 13.2 14.5 11.8Z" fill="#76A9FA"/>
      </svg>
      <span className="agents-title">Paper2Exp</span>
      <span className="topbar-sub">reproduction demo</span>
    </div>
    <div className="topbar-right">
      {children}
      <button type="button" className="icon-btn" onClick={onTheme} aria-label="Toggle dark mode">{dark ? <Sun size={15}/> : <Moon size={15}/>}</button>
    </div>
  </header>;
}

/** The author line of an AI message: the vendor's logo in a thin circle and its name (Alex's ResponseAuthor). */
function Author({vendor, name}: {vendor: string; name?: string}) {
  const provider = {id: vendor, name: VENDOR_NAME[vendor] ?? vendor, models: [],
    icon: ['anthropic', 'openai', 'google', 'xai'].includes(vendor) ? undefined : <VendorLogo vendor={vendor} size={14}/>};
  return <div className="assistant-heading">
    <span className="assistant-avatar" aria-hidden><ProviderGlyph provider={provider} className="size-3.5"/></span>
    <span>{name ?? provider.name}</span>
  </div>;
}

/* ---------------------------------------------------------------- results */

/** match / close / mismatch / unknown for one answer, and how to say it: against the paper, or CORE-Bench's grade. */
function verdictOf(a: Answer): {status: Comparison['status']; label: string} {
  const corebench = a.reference?.source === 'corebench';
  if (a.answer === null || a.answer === undefined) return {status: 'unknown', label: 'No answer'};
  if (corebench && a.correct !== undefined && a.correct !== null)
    return a.correct ? {status: 'match', label: 'Matches reference'} : {status: 'mismatch', label: 'Differs from reference'};
  const status = a.comparison?.status ?? 'unknown';
  return {status, label: {match: 'Matches paper', close: 'Close to paper', mismatch: 'Differs from paper',
    unknown: a.reference ? 'Cannot compare' : 'Not in paper'}[status]};
}

function gap(c?: Comparison, unit = '') {
  if (c?.diff === undefined) return '—';
  const pct = c.rel === undefined || c.rel === null || c.rel < 0.001 ? '' : ` (${(c.rel * 100).toFixed(c.rel < 0.1 ? 1 : 0)}%)`;
  return `${c.diff > 0 ? '+' : ''}${show(+c.diff.toPrecision(3))}${unit}${pct}`;
}

/** The reproduction's results: a summary, one table row per question (answer, reference, gap, verdict) with its
 *  details folded under it, then the figures the run made. */
function Results({job, jobKey}: {job: JobState; jobKey: string}) {
  const answers = job.answers ?? [];
  const corebench = answers.some(a => a.reference?.source === 'corebench');
  const refName = corebench ? 'Reference' : 'Paper';
  const verdicts = answers.map(verdictOf);
  const compared = answers.filter(a => a.reference).length;
  const matched = verdicts.filter(v => v.status === 'match').length;
  const answered = answers.filter(a => a.answer !== null && a.answer !== undefined).length;
  const arxiv = answers.find(a => a.reference?.arxiv)?.reference?.arxiv;
  const figures = [...new Set(answers.flatMap(a => [...a.evidence, ...(a.provenance?.produced_in ?? [])])
    .map(p => p.replace(/ \(viewed figure\)$/, '')).filter(p => FIGURE.test(p) && !p.startsWith('logs/')))].slice(0, 4);
  const overall = compared === 0 ? 'unknown' : matched === compared ? 'match' : matched === 0 ? 'mismatch' : 'close';
  return <section className="results">
    <div className={`results-summary is-${overall}`}>
      <div className="results-score">
        <b>{compared ? `${matched} / ${compared}` : `${answered} / ${answers.length}`}</b>
        <span>{compared ? `match the ${corebench ? 'reference answers' : 'paper'}` : 'answered (nothing to compare with)'}</span>
      </div>
      <div className="results-facts">
        <span><i>Answered</i>{answered} / {answers.length}</span>
        {job.summary && <span><i>Time</i>{minutes(job.summary.wall_s)}</span>}
        <span><i>Cost</i>${(job.cost ?? 0).toFixed(3)}</span>
        <span><i>Workflow</i>{WF_LABEL[job.workflow] ?? job.workflow}</span>
        <span><i>Model</i>{job.profile}</span>
        {arxiv && <span><i>Paper</i><a href={`https://arxiv.org/abs/${arxiv}`} target="_blank" rel="noreferrer">arXiv {arxiv}</a></span>}
      </div>
    </div>
    <div className="results-wrap">
      <table className="results-table">
        <colgroup><col className="c-id"/><col/><col className="c-num"/><col className="c-num"/><col className="c-num"/><col className="c-verdict"/></colgroup>
        <thead><tr><th>#</th><th>Question</th><th>Reproduced</th><th>{refName}</th><th>Gap</th><th>Verdict</th></tr></thead>
        <tbody>{answers.map((a, i) => {
          const unit = a.reference?.unit ? ` ${a.reference.unit}` : '';
          const v = verdicts[i];
          const none = a.answer === null || a.answer === undefined;
          return [
            <tr key={a.id} className={`is-${v.status}`}>
              <td className="mono">{a.id}</td>
              <td className="q">{a.question}</td>
              <td className="num" title={none ? undefined : JSON.stringify(a.answer)}>{none ? '—' : `${show(a.answer)}${unit}`}</td>
              <td className="num" title={a.reference ? JSON.stringify(a.reference.value) : undefined}>{a.reference ? `${show(a.reference.value)}${unit}` : '—'}</td>
              <td className="num" title={a.comparison?.diff !== undefined ? String(a.comparison.diff) : undefined}>{gap(a.comparison, unit)}</td>
              <td><span className={`verdict is-${v.status}`}>{v.status === 'match' ? <Check size={12}/> : v.status === 'mismatch' ? <X size={12}/> : null}{v.label}</span></td>
            </tr>,
            <tr key={`${a.id}-d`} className="details-row"><td/><td colSpan={5}>
              <details><summary>Source, evidence and notes</summary>
                <dl>
                  {a.reference?.location && <><dt>{refName} value</dt><dd>{a.reference.location}{a.reference.quote ? <q>{a.reference.quote}</q> : null}</dd></>}
                  {a.provenance && <><dt>Answer source</dt><dd><span className={`prov is-${a.provenance.status}`}>{PROVENANCE[a.provenance.status] ?? a.provenance.status}</span></dd></>}
                  {a.evidence.length > 0 && <><dt>Evidence</dt><dd>{a.evidence.map(e => <code key={e}>{e}</code>)}</dd></>}
                  {a.note && <><dt>Agent’s note</dt><dd>{a.note}</dd></>}
                </dl>
              </details>
            </td></tr>,
          ];
        })}</tbody>
      </table>
    </div>
    {figures.length > 0 && <div className="results-figs">
      <div className="results-figs-head">Figures this run made</div>
      <div className="results-figs-grid">{figures.map(p => IMAGE.test(p)
        ? <a key={p} href={api.fileUrl(jobKey, p)} target="_blank" rel="noreferrer" className="fig"><img src={api.fileUrl(jobKey, p)} alt={p}
          onError={e => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none'; }}/><span>{p}</span></a>
        : <a key={p} href={api.fileUrl(jobKey, p)} target="_blank" rel="noreferrer" className="fig is-file"><span>Open {p}</span></a>)}</div>
    </div>}
  </section>;
}

/* ---------------------------------------------------------------- chat messages */

function RunMessage({msg, job, wall, selectedId, onSelect, onStop}: {msg: Extract<Msg, {type: 'run'}>;
  job: JobState | null; wall: number; selectedId: string | null; onSelect: (id: string | null) => void; onStop: () => void}) {
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!full) return;
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setFull(false); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [full]);
  if (!job) return <div className="bubble"><span className="thinking"><Loader2 size={14} className="spin"/>Starting…</span></div>;
  const live = isLive(job);
  const c = current(job.nodes);
  const fallback = live ? job.nodes[0] : [...job.nodes].reverse().find(n => n.steps.length) ?? job.nodes[0];
  const selected = job.nodes.find(n => n.id === (selectedId ?? c?.node.id ?? fallback?.id)) ?? fallback;
  const outcome: RunOutcome = selected?.status === 'failed' ? 'error' : selected?.status === 'stopped' ? 'stopped' : 'done';
  const elapsed = job.summary && !live ? job.summary.wall_s : job.started ? Math.max(0, (wall - Date.parse(job.started)) / 1000) : 0;
  const provider = job.vendor ?? 'anthropic';
  let status: ReactNode;
  if (job.phase === 'preparing') status = <><Loader2 size={13} className="spin"/><span>Preparing the workspace…</span></>;
  else if (live && c) status = <><span className="now-live"/>{(() => { const I = ROLE_ICONS[c.node.kind]; return <I size={14}/>; })()}
    <span><b>{c.node.role}</b>{c.step ? <> · {c.step.label}{c.step.target ? <code>{c.step.target}</code> : null}</> : ' · thinking…'}</span></>;
  else if (live) status = <><Loader2 size={13} className="spin"/><span>{job.nodes[0]?.status === 'waiting' ? `${job.nodes[0].role} is waiting for its workers and commands…` : 'The agent is thinking…'}</span></>;
  else if (job.phase === 'done') status = <><Check size={13}/><span>Finished. The results are below.</span></>;
  else status = <><X size={13}/><span>{job.phase === 'stopped' ? 'Stopped' : `The run failed${job.error ? `: ${job.error.slice(0, 200)}` : ''}`}</span></>;
  return <div className="bubble run-bubble">
    <p>Reproducing “{job.spec?.title ?? ''}”. The window shows every agent and the step it is on; click a card to see all its steps.</p>
    <div className={`run-window${full ? ' is-full' : ''}`}>
      <div className="run-window-head">
        <div className={`run-status is-${job.phase}`}>{status}</div>
        <div className="chips">
          <span className="chip">{WF_LABEL[job.workflow] ?? job.workflow}</span>
          <span className="chip"><VendorLogo vendor={provider} size={12}/>{job.profile}</span>
          {job.spec?.code && <span className="chip">{job.spec.code.capsule ? <Package size={11}/> : <Github size={11}/>}{job.spec.code.capsule ?? job.spec.code.repo_url?.replace('https://github.com/', '')}</span>}
          <span className="chip clock">{minutes(elapsed)}</span>
        </div>
        <div className="row">
          {live && <button type="button" className="btn ghost sm" onClick={onStop}><Square size={11}/>Stop</button>}
          <button type="button" className="btn ghost sm" onClick={() => setFull(f => !f)} aria-label={full ? 'Exit full screen' : 'Full screen'}>
            {full ? <Minimize2 size={13}/> : <Maximize2 size={13}/>}</button>
        </div>
      </div>
      <div className="run-window-body">
        <div className="graph-scroll">
          {job.nodes.length > 0 && <OrchestrationGraph nodes={job.nodes} provider={provider} now={wall}
            currentId={live ? c?.node.id ?? null : null} selectedId={selectedId ?? (live ? c?.node.id ?? null : null)}
            onSelect={id => onSelect(id === selectedId ? null : id)}/>}
        </div>
        {selected && <div className="run-side">
          <div className="side-label">{selectedId ? <>Selected: {selected.role}<button type="button" className="link" onClick={() => onSelect(null)}>Follow current</button></>
            : live ? 'Following the current agent' : 'Last agent at work'}</div>
          <AgentRun key={selected.id} steps={selected.steps} live={live && (selected.status === 'running' || selected.status === 'waiting')}
            outcome={outcome} badge={<Avatar provider={provider} kind={selected.kind}/>} iconFor={toolIcon}
            meta={<span>{selected.role}{selected.model ? ` · ${selected.model}` : ''}</span>}
            liveText={selected.status === 'waiting' ? 'Waiting for workers and commands…' : 'Thinking…'}
            extra={selected.summary ? <p className="side-summary">{selected.summary}</p> : undefined}/>
        </div>}
      </div>
    </div>
    {job.answers && <Results job={job} jobKey={msg.key}/>}
  </div>;
}

function SpecMessage({msg, onStart, busy}: {msg: Extract<Msg, {type: 'spec'}>; onStart: () => void; busy: boolean}) {
  const {spec} = msg;
  const refName = msg.paper.source === 'corebench' ? 'Reference' : 'Paper';
  return <div className="bubble">
    <p>{msg.cost ? `Here is your request as a task (drafting cost $${msg.cost.toFixed(4)}). ` : 'Here is the example task. '}
      {msg.started ? 'It has started.' : 'Press Start or reply “start”; to change it, just say what to change.'}</p>
    <div className="spec-card">
      <div className="spec-head"><FlaskConical size={15}/><b>{spec.title}</b></div>
      <div className="chips"><span className="chip">{spec.code.capsule ? <><Package size={11}/>{spec.code.capsule}</> : <><Github size={11}/>{spec.code.repo_url?.replace('https://github.com/', '')}</>}</span>
        {spec.language && <span className="chip">{spec.language}</span>}</div>
      <p className="spec-task">{spec.task_prompt}</p>
      <ol className="spec-qs">{spec.questions.map(q => {
        const ref = msg.paper.values[q.id];
        return <li key={q.id}><code>{q.id}</code>{q.text}<span className="muted"> · {q.answer_type}</span>
          {ref && <div className="paper-ref">{refName}: <b>{show(ref.value)}{ref.unit ? ` ${ref.unit}` : ''}</b>{ref.location ? <span className="muted"> ({ref.location})</span> : null}</div>}</li>;
      })}</ol>
      <div className="paper-note">{msg.paper.source === 'corebench'
        ? <>A CORE-Bench task: the answers are compared with its reference answers (the mean of 3 manual re-runs), which the agents never see.</>
        : msg.paper.arxiv
          ? <>Paper <a href={`https://arxiv.org/abs/${msg.paper.arxiv}`} target="_blank" rel="noreferrer">arXiv {msg.paper.arxiv}</a>: found its value for {Object.keys(msg.paper.values).length} of {spec.questions.length} questions; the answers are compared with them at the end. The agents never see these values.</>
          : <>No paper found (no arXiv link in the message or the README), so the answers cannot be compared. Add an arXiv link to the message to compare.</>}</div>
    </div>
    {!msg.started && <div className="actions"><button type="button" className="btn primary sm" disabled={busy} onClick={onStart}>
      {busy ? <Loader2 size={14} className="spin"/> : <Play size={13}/>}Start</button></div>}
  </div>;
}

function AskUrlMessage({msg, onSubmit}: {msg: Extract<Msg, {type: 'ask_url'}>; onSubmit: (url: string) => void}) {
  const [url, setUrl] = useState('');
  const ok = GITHUB.test(url.trim());
  return <div className="bubble">
    <p>Your request has no code to run. What is the <b>GitHub address</b> of the official code? The agents clone it and reproduce from there. Enter it below, or reply with it.</p>
    {!msg.resolved && <form className="url-form" onSubmit={e => { e.preventDefault(); if (ok) onSubmit(url.trim()); }}>
      <Github size={15}/><input className="input" placeholder="https://github.com/owner/repo" value={url} onChange={e => setUrl(e.target.value)} autoFocus/>
      <button type="submit" className="btn primary sm" disabled={!ok}>Continue</button>
    </form>}
  </div>;
}

/* ---------------------------------------------------------------- app */

export function App() {
  const [options, setOptions] = useState<Options | null>(null);
  const [examples, setExamples] = useState<ExampleTask[] | null>(null);
  const [history, setHistory] = useState<HistoryRun[] | null>(null);
  const [error, setError] = useState('');
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [workdir, setWorkdir] = useState<Workdir | null>(null);
  const [page, setPage] = useState<'chat' | 'changelog'>(() => window.location.hash === '#changelog' ? 'changelog' : 'chat');
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [workflow, setWorkflow] = useState('planner_workers');
  const [model, setModel] = useState('haiku55');
  const [key, setKey] = useState<string | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [wall, setWall] = useState(Date.now());
  const [dark, setDark] = useState(() => { try { return localStorage.getItem('p2e-theme') === 'dark'; } catch { return false; } });
  const thread = useRef<HTMLDivElement>(null);
  const stick = useRef(true);  // the thread follows new content while the user is at its bottom

  const vendor = options?.models.find(m => m.id === model)?.vendor ?? 'anthropic';
  const push = useCallback((m: NewMsg, by?: string) => {
    stick.current = true;
    setMsgs(ms => [...ms.filter(x => !(x.role === 'assistant' && x.type === 'thinking')), {...m, id: newId(), by: by ?? vendor} as Msg]);
  }, [vendor]);
  const patch = useCallback((mid: number, f: (m: Msg) => Msg) => setMsgs(ms => ms.map(m => m.id === mid ? f(m) : m)), []);
  const refreshHistory = useCallback(() => { api.history().then(r => setHistory(r.runs), () => setHistory([])); }, []);

  useEffect(() => {
    api.options().then(setOptions, e => setError((e as Error).message));
    api.examples().then(r => setExamples(r.examples), () => setExamples([]));
    api.workdir().then(setWorkdir, () => undefined);
    refreshHistory();
  }, [refreshHistory]);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try { localStorage.setItem('p2e-theme', dark ? 'dark' : 'light'); } catch { /* private mode */ }
  }, [dark]);
  useEffect(() => { const t = setInterval(() => setWall(Date.now()), 500); return () => clearInterval(t); }, []);
  // keep the newest content in view: new messages, the run window as it appears, the results when they arrive
  useEffect(() => {
    const el = thread.current;
    if (el && stick.current) el.scrollTo({top: el.scrollHeight, behavior: 'smooth'});
  }, [msgs.length, job?.phase, job?.nodes.length, job?.answers?.length]);

  const open = useCallback((k: string) => {
    setKey(k); setJob(null); setSelectedId(null);
    window.location.hash = `job=${k}`;
    push({role: 'assistant', type: 'run', key: k});
  }, [push]);

  // a link with #job= opens that run; #changelog opens the changelog (and the browser's back button leaves it)
  useEffect(() => { const h = fromHash(); if (h) open(h); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onHash = () => setPage(window.location.hash === '#changelog' ? 'changelog' : 'chat');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const showChangelog = () => { window.location.hash = 'changelog'; };
  const leaveChangelog = () => { window.location.hash = key ? `job=${key}` : ''; setPage('chat'); };

  // poll every second while the run is alive
  useEffect(() => {
    if (!key) return;
    let stop = false, timer = 0;
    const tick = async () => {
      try {
        const s = await api.job(key);
        if (stop) return;
        setJob(s);
        if (isLive(s)) timer = window.setTimeout(tick, 1000);
        else { refreshHistory(); api.examples().then(r => setExamples(r.examples), () => undefined); }
      } catch (e) { if (!stop) { setError((e as Error).message); timer = window.setTimeout(tick, 3000); } }
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [key, refreshHistory]);

  const draftSpec = useCallback(async (prompt: string, repoUrl?: string) => {
    setBusy(true);
    push({role: 'assistant', type: 'thinking'});
    try {
      const r = await api.draft({prompt, model, ...(repoUrl ? {repo_url: repoUrl} : {})});
      if ('need' in r) push({role: 'assistant', type: 'ask_url', prompt});
      else push({role: 'assistant', type: 'spec', spec: r.spec, paper: r.paper, cost: r.cost});
    } catch (e) { push({role: 'assistant', type: 'text', text: `Could not draft the task: ${(e as Error).message}`}); }
    finally { setBusy(false); }
  }, [push, model]);

  const start = useCallback(async (mid: number, spec: Spec) => {
    setBusy(true);
    try {
      const r = await api.start({spec, workflow, model});
      patch(mid, m => ({...m, started: true} as Msg));
      open(r.key);
      refreshHistory();
    } catch (e) { push({role: 'assistant', type: 'text', text: `Could not start: ${(e as Error).message}`}); }
    finally { setBusy(false); }
  }, [workflow, model, patch, open, push, refreshHistory]);

  const resolveUrl = useCallback((mid: number, prompt: string, url: string) => {
    patch(mid, m => ({...m, resolved: true} as Msg));
    draftSpec(`${prompt}\nCode: ${url}`, url);
  }, [patch, draftSpec]);

  const send = useCallback((text: string) => {
    push({role: 'user', text});
    const last = [...msgs].reverse().find(m => m.role === 'assistant' && m.type !== 'thinking');
    const url = GITHUB.exec(text)?.[0];
    if (last?.role === 'assistant' && last.type === 'ask_url' && !last.resolved) {  // the answer to "which repository?"
      if (url) resolveUrl(last.id, last.prompt, url);
      else push({role: 'assistant', type: 'text', text: 'I could not find a GitHub address in that. Please send a link like https://github.com/owner/repo.'});
      return;
    }
    if (last?.role === 'assistant' && last.type === 'spec' && !last.started) {
      if (START_WORDS.test(text.trim())) { start(last.id, last.spec); return; }
      // a correction to the drafted task: draft it again with the correction
      draftSpec(`${last.spec.origin.prompt}\nAlso: ${text}`, url ?? last.spec.code.repo_url ?? undefined);
      return;
    }
    draftSpec(text, url);
  }, [msgs, push, resolveUrl, draftSpec, start]);

  // an example: its task as a new spec, started at once with the workflow and model chosen now
  const runExample = useCallback(async (e: ExampleTask) => {
    push({role: 'user', text: `Run the example “${e.title}” (${WF_LABEL[workflow]} · ${model})`});
    setBusy(true);
    try {
      const r = await api.example(e.case);
      const r2 = await api.start({spec: r.spec, workflow, model});
      push({role: 'assistant', type: 'spec', spec: r.spec, paper: r.paper, cost: 0, started: true});
      open(r2.key);
      refreshHistory();
    } catch (err) { push({role: 'assistant', type: 'text', text: `Could not start: ${(err as Error).message}`}); }
    finally { setBusy(false); }
  }, [push, open, workflow, model, refreshHistory]);

  const stop = useCallback(() => { if (key) api.stop(key).catch(() => undefined); }, [key]);
  const lastRun = [...msgs].reverse().find(m => m.role === 'assistant' && m.type === 'run');

  return <div className={`app${page === 'changelog' ? ' is-changelog' : ''}`}>
    <TopBar dark={dark} onTheme={() => setDark(d => !d)}>
      <HistoryMenu runs={history} onRefresh={refreshHistory} onOpen={r => { leaveChangelog(); push({role: 'user', text: `Open “${r.title}”`}); open(r.key); }}/>
      <button type="button" className={`menu-trigger${page === 'changelog' ? ' is-open' : ''}`} onClick={showChangelog}><ListChecks size={14}/><span>Changelog</span></button>
    </TopBar>
    {page === 'changelog' && <ChangelogPage onBack={leaveChangelog}/>}
    {error && !options && <div className="error page-error">Cannot reach the server: {error} (start it with <code>p2e demo serve</code>)</div>}
    <main className={`layout${msgs.length ? '' : ' is-empty'}${page === 'changelog' ? ' is-hidden' : ''}`}>
      <section className="chat">
        {!msgs.length && <div className="hero">
          <h1>What should we reproduce?</h1>
          <p>Name the paper or code and the numbers or figures you want, ideally with the GitHub address. I’ll turn it into a task,
            run it with the workflow and model below, and compare the results with the paper.</p>
          <div className="suggest">{SUGGESTIONS.map(x => <button type="button" key={x.label} className="suggest-btn" onClick={() => setDraft(x.text)}>{x.label}</button>)}</div>
        </div>}
        <div className="thread" ref={thread} onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
          {msgs.map(m => m.role === 'user'
            ? <div key={m.id} className="msg user"><div className="bubble">{m.text}</div></div>
            : <div key={m.id} className={`msg assistant${m.type === 'run' ? ' is-wide' : ''}`}>
              <Author vendor={m.type === 'run' && m.id === lastRun?.id && job?.vendor ? job.vendor : m.by}/>
              {m.type === 'thinking' ? <div className="bubble"><div className="thinking-row"><Loader variant="newton" size={28}/><ShiningText text="Drafting the task and looking up the paper’s values…"/></div></div>
                : m.type === 'text' ? <div className="bubble"><p>{m.text}</p></div>
                : m.type === 'ask_url' ? <AskUrlMessage msg={m} onSubmit={u => { push({role: 'user', text: u}); resolveUrl(m.id, m.prompt, u); }}/>
                : m.type === 'spec' ? <SpecMessage msg={m} busy={busy} onStart={() => start(m.id, m.spec)}/>
                : m.id === lastRun?.id ? <RunMessage msg={m} job={job} wall={wall} selectedId={selectedId} onSelect={setSelectedId} onStop={stop}/>
                : <div className="bubble"><p className="muted">An earlier run; open it again from History.</p></div>}
            </div>)}
        </div>
        {options && <Composer options={options} examples={examples} workdir={workdir} onWorkdir={setWorkdir} onSend={send}
          onExample={e => { if (!busy) runExample(e); }} busy={busy} onStop={isLive(job) ? stop : undefined}
          workflow={workflow} setWorkflow={setWorkflow} model={model} setModel={setModel} draft={draft} setDraft={setDraft}/>}
      </section>
    </main>
  </div>;
}
