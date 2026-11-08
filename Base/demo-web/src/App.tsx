// The demo as an agent chat: the user says what to reproduce, the assistant turns it into a task (asking for the GitHub
// address when the message has none), starts the chosen workflow on a yes, and reports in the thread: the run's message
// is a fixed-size window with the live agent graph (scaled to fit) and the selected agent's steps, then a table of the
// results against the paper. The message box (Composer) picks the workflow, the model, the run folder and the example
// tasks; the top bar reopens the user's earlier runs. AI messages carry the model vendor's logo, as in Alex.
import {useCallback, useEffect, useRef, useState, type ReactNode} from 'react';
import {Check, ChevronDown, Clock, FlaskConical, Github, History, Languages, ListChecks, Loader2, Maximize2, Minimize2, Moon, Package, Play, Square, Sun, X} from 'lucide-react';
import {api} from './api';
import {AgentRun, type RunOutcome} from './agent-run/agent-run';
import {OrchestrationGraph} from './graph/OrchestrationGraph';
import {Avatar, ROLE_ICONS, toolIcon} from './icons';
import {VendorLogo} from './provider-logos';
import {Composer, VENDOR_NAME, wfLabel} from './Composer';
import {useLang, type Lang} from './i18n';
import {ChangelogPage} from './Changelog';
import {ProviderGlyph} from './alex/modules/chat/components/ui/model-picker';
import {Loader} from './alex/modules/chat/components/ui/loader';
import {ShiningText} from './alex/modules/chat/components/ui/shining-text';
import type {Answer, Comparison, ExampleTask, GraphNode, HistoryRun, JobState, Options, PaperValues, Presence, Spec, Workdir} from './types';

const PROVENANCE: Record<string, [string, string]> = {produced: ['Produced by this run', '由本次运行产生'],
  typed: ['Only in text the agent wrote itself', '只出现在 agent 自己写的文字里'],
  preexisting_only: ['Only in files shipped with the code', '只出现在代码自带的文件里'], not_found: ['Not found in the run’s output', '运行输出中找不到']};
const IMAGE = /\.(png|jpe?g|gif|svg|webp)$/i;
const FIGURE = /\.(png|jpe?g|gif|svg|webp|pdf)$/i;
const GITHUB = /https?:\/\/(?:www\.)?github\.com\/[\w.-]+\/[\w.-]+/;
const START_WORDS = /^(start|go|yes|ok|okay|run|run it|开始|开始吧|好|好的|可以|确认|运行)[.!。！]?$/i;

export const SUGGESTIONS: Record<Lang, {label: string; text: string}[]> = {
  en: [
    {label: 'KalmanNet, Table I (signal processing, ~5 min)', text: 'Using the official code https://github.com/KalmanNet/KalmanNet_TSP on CPU, reproduce the Test T = 20 row of Table I of the KalmanNet paper: linear 2x2 state-space model (F in canonical form, H = I, full information, nu = 0 dB, 1/r^2 = 20 dB), trained and tested on trajectories of length T = 20. Report the test MSE (dB) of KalmanNet and of the Kalman filter with the true F, H, Q, R.'},
    {label: 'A request without the code’s address', text: 'Reproduce the T = 20 row of Table I of the KalmanNet paper: the test MSE of KalmanNet and of the Kalman filter.'},
  ],
  zh: [
    {label: 'KalmanNet 表 I（信号处理，约 5 分钟）', text: '用官方代码 https://github.com/KalmanNet/KalmanNet_TSP 在 CPU 上复现 KalmanNet 论文表 I 中 Test T = 20 这一行：线性 2x2 状态空间模型（F 为标准型，H = I，full information，nu = 0 dB，1/r^2 = 20 dB），训练和测试轨迹长度都是 T = 20。报告 KalmanNet 和使用真实 F、H、Q、R 的 Kalman filter 的测试 MSE（dB）。'},
    {label: '一个没给代码地址的请求', text: '复现 KalmanNet 论文表 I 中 T = 20 这一行：KalmanNet 和 Kalman filter 的测试 MSE。'},
  ],
};

// every AI message records the vendor of the model that wrote it, for its author line
type Msg =
  | {id: number; role: 'user'; text: string}
  | {id: number; role: 'assistant'; by: string; type: 'thinking'; steps?: string[]; note?: string}
  | {id: number; role: 'assistant'; by: string; type: 'text'; text: string}
  | {id: number; role: 'assistant'; by: string; type: 'ask_url'; prompt: string; resolved?: boolean}
  | {id: number; role: 'assistant'; by: string; type: 'spec'; spec: Spec; paper: PaperValues; cost: number; started?: boolean;
      example?: boolean; reveal?: boolean}
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

// How a plan appears: the drafting steps tick off one by one, then the card fills in (title, task typed out, questions,
// then the paper's values). Without motion (prefers-reduced-motion) it appears at once.
const PLAN_STEP_MS = 900;
const reducedMotion = () => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** When each part of a plan card appears, in ms after the card does. */
function revealTimeline(spec: Spec, paper: PaperValues) {
  const chips = 250, task = 550;
  const typeMs = Math.min(2600, Math.max(900, spec.task_prompt.length * 4));
  const q0 = task + typeMs + 250, qStep = 450;
  const refs = spec.questions.filter(q => paper.values[q.id]).length;
  const r0 = q0 + spec.questions.length * qStep + 300, rStep = 400;
  const note = r0 + refs * rStep + 200;
  return {chips, task, typeMs, q0, qStep, r0, rStep, note, end: note + 350};
}

const isLive = (job: JobState | null) => !!job && (job.phase === 'running' || job.phase === 'preparing' || job.phase === 'queued');
export const minutes = (s: number, lang: Lang = 'en') => s < 60 ? `${Math.round(s)} ${lang === 'zh' ? '秒' : 's'}`
  : `${(s / 60).toFixed(s < 600 ? 1 : 0)} ${lang === 'zh' ? '分钟' : 'min'}`;
const ago = (t: number, lang: Lang) => {
  const s = Date.now() / 1000 - t, zh = lang === 'zh';
  return s < 3600 ? `${Math.max(1, Math.round(s / 60))} ${zh ? '分钟前' : 'min ago'}` : s < 86400 ? `${Math.round(s / 3600)} ${zh ? '小时前' : 'h ago'}`
    : `${Math.round(s / 86400)} ${zh ? '天前' : 'd ago'}`;
};

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
  const {lang, L} = useLang();
  return <div onMouseDown={onRefresh}>
    <Menu wide label={<><History size={14}/><span>{L('History', '历史记录')}</span></>}>
      {close => <>
        <div className="menu-head">{L('Your reproductions, newest first. Open one to see its graph and results again.', '你的复现记录，最新的在前。打开一条可以重新查看它的 agent 图和结果。')}</div>
        <div className="menu-scroll">
          {!runs ? <div className="menu-empty"><Loader2 size={14} className="spin"/></div>
            : !runs.length ? <div className="menu-empty">{L('Nothing yet: ask for a reproduction or pick an example', '还没有记录：发一个复现请求，或者选一个示例任务')}</div>
            : runs.map(r => <button type="button" key={r.key} role="menuitem" className="menu-item" onClick={() => { close(); onOpen(r); }}>
              <span className={`menu-dot is-${r.status}`} title={r.status}/>
              <span className="menu-main"><b>{r.title}</b>
                <small>{wfLabel(r.workflow, lang)} · {r.profile}{r.wall_s ? ` · ${minutes(r.wall_s, lang)}` : ''}{r.cost ? ` · $${r.cost.toFixed(3)}` : ''}
                  {r.answered !== null && r.answered !== undefined ? ` · ${L(`${r.answered}/${r.questions} answered`, `已回答 ${r.answered}/${r.questions}`)}` : ''}</small></span>
              <span className="menu-meta">{r.status === 'running' ? L('running', '运行中') : r.started ? ago(r.started, lang) : ''}</span>
            </button>)}
        </div>
      </>}
    </Menu>
  </div>;
}

/** One id per browser, so several tabs of one person count once. */
function clientId() {
  try {
    let id = localStorage.getItem('p2e-client');
    if (!id) { id = Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem('p2e-client', id); }
    return id;
  } catch { return 'anonymous'; }
}

/** People on the site now, runs going and runs waiting: this page says it is here every 15 s and reads the answer. */
function OnlineStatus() {
  const {L} = useLang();
  const [p, setP] = useState<Presence | null>(null);
  useEffect(() => {
    const id = clientId();
    let stop = false;
    const beat = () => api.presence(id).then(r => { if (!stop) setP(r); }, () => undefined);
    beat();
    const t = setInterval(beat, 15000);
    const onVisible = () => { if (document.visibilityState === 'visible') beat(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { stop = true; clearInterval(t); document.removeEventListener('visibilitychange', onVisible); };
  }, []);
  if (!p) return null;
  const full = p.max_running != null && p.running >= p.max_running;
  const others = p.online - p.names.length;  // pages open without a name (a server without an access code)
  const signOut = async () => { await api.logout(); window.location.reload(); };
  return <Menu wide label={<span className="online-pill">
    <span className="online-dot"/><b>{p.online}</b><span>{L('online', '在线')}</span>
    <span className="online-sep"/>
    <span className={`online-runs${full ? ' is-full' : ''}`}><b>{p.running}</b>{p.max_running != null ? <i>/{p.max_running}</i> : null}<span>{L('running', '运行中')}</span></span>
    {p.queued > 0 && <><span className="online-sep"/><span className="online-queue"><Clock size={12}/><b>{p.queued}</b><span>{L('queued', '排队')}</span></span></>}
  </span>}>
    {close => <>
      <div className="menu-head">{L(`${p.online} online now`, `当前 ${p.online} 人在线`)}</div>
      <div className="menu-scroll">
        {p.names.map(n => <div key={n} className="menu-item online-person"><span className="online-dot"/>
          <span className="menu-main"><b>{n}</b></span>{n === p.me && <span className="menu-meta">{L('you', '你')}</span>}</div>)}
        {others > 0 && <div className="menu-item online-person"><span className="online-dot"/>
          <span className="menu-main"><b>{L(`${others} without a name`, `${others} 位未署名`)}</b></span></div>}
      </div>
      <div className="menu-head online-note">{p.max_running != null
        ? L(`${p.running} of ${p.max_running} run slots busy${p.queued ? `, ${p.queued} waiting` : ''}. A new run waits in line when all are busy and starts by itself.`,
          `运行名额 ${p.running}/${p.max_running}${p.queued ? `，${p.queued} 个在排队` : ''}。名额用满时新的任务会排队，轮到时自动开始。`)
        : L(`${p.running} running`, `${p.running} 个运行中`)}</div>
      {p.me && <button type="button" className="menu-item online-signout" onClick={() => { close(); signOut(); }}>
        <span className="menu-main"><b>{L(`Sign out (${p.me})`, `退出登录（${p.me}）`)}</b><small>{L('To come back under another name', '可换一个名字重新进入')}</small></span></button>}
    </>}
  </Menu>;
}

/** The language of the whole site, English or Chinese; remembered in this browser. */
function LanguageMenu() {
  const {lang, setLang} = useLang();
  const choices: [Lang, string][] = [['en', 'English'], ['zh', '中文']];
  return <Menu label={<><Languages size={14}/><span>{lang === 'zh' ? '中文' : 'English'}</span></>} title={lang === 'zh' ? '语言' : 'Language'}>
    {close => choices.map(([id, name]) => <button type="button" key={id} role="menuitemradio" aria-checked={lang === id}
      className={`menu-item menu-lang${lang === id ? ' is-on' : ''}`} onClick={() => { setLang(id); close(); }}>
      <span className="menu-main"><b>{name}</b></span>{lang === id && <Check size={14}/>}</button>)}
  </Menu>;
}

function TopBar({dark, onTheme, children}: {dark: boolean; onTheme: () => void; children: ReactNode}) {
  const {L} = useLang();
  return <header className="topbar app-topbar">
    <div className="topbar-left">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M8.5 2.5C8.7 6.1 9.9 7.3 13.5 7.5C9.9 7.7 8.7 8.9 8.5 12.5C8.3 8.9 7.1 7.7 3.5 7.5C7.1 7.3 8.3 6.1 8.5 2.5Z" fill="#2E7CF6"/>
        <path d="M14.5 11.8C14.6 13.2 15.1 13.7 16.5 13.8C15.1 13.9 14.6 14.4 14.5 15.8C14.4 14.4 13.9 13.9 12.5 13.8C13.9 13.7 14.4 13.2 14.5 11.8Z" fill="#76A9FA"/>
      </svg>
      <span className="agents-title">Paper2Exp</span>
      <span className="topbar-sub">{L('reproduction demo', '论文复现演示')}</span>
    </div>
    <div className="topbar-right">
      <OnlineStatus/>
      {children}
      <LanguageMenu/>
      <button type="button" className="icon-btn" onClick={onTheme} aria-label={L('Toggle dark mode', '切换深色模式')}>{dark ? <Sun size={15}/> : <Moon size={15}/>}</button>
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
function verdictOf(a: Answer, lang: Lang): {status: Comparison['status']; label: string} {
  const zh = lang === 'zh';
  const corebench = a.reference?.source === 'corebench';
  if (a.answer === null || a.answer === undefined) return {status: 'unknown', label: zh ? '没有答案' : 'No answer'};
  if (corebench && a.correct !== undefined && a.correct !== null)
    return a.correct ? {status: 'match', label: zh ? '与参考答案一致' : 'Matches reference'} : {status: 'mismatch', label: zh ? '与参考答案不符' : 'Differs from reference'};
  const status = a.comparison?.status ?? 'unknown';
  return {status, label: (zh ? {match: '与论文一致', close: '接近论文', mismatch: '与论文不符', unknown: a.reference ? '无法比较' : '论文中没有'}
    : {match: 'Matches paper', close: 'Close to paper', mismatch: 'Differs from paper', unknown: a.reference ? 'Cannot compare' : 'Not in paper'})[status]};
}

function gap(c?: Comparison, unit = '') {
  if (c?.diff === undefined) return '—';
  const pct = c.rel === undefined || c.rel === null || c.rel < 0.001 ? '' : ` (${(c.rel * 100).toFixed(c.rel < 0.1 ? 1 : 0)}%)`;
  return `${c.diff > 0 ? '+' : ''}${show(+c.diff.toPrecision(3))}${unit}${pct}`;
}

/** The reproduction's results: a summary, one table row per question (answer, reference, gap, verdict) with its
 *  details folded under it, then the figures the run made. */
function Results({job, jobKey}: {job: JobState; jobKey: string}) {
  const {lang, L} = useLang();
  const answers = job.answers ?? [];
  const corebench = answers.some(a => a.reference?.source === 'corebench');
  const refName = corebench ? L('Reference', '参考答案') : L('Paper', '论文');
  const verdicts = answers.map(a => verdictOf(a, lang));
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
        <span>{compared ? L(`match the ${corebench ? 'reference answers' : 'paper'}`, corebench ? '与参考答案一致' : '与论文一致') : L('answered (nothing to compare with)', '已回答（没有可比较的值）')}</span>
      </div>
      <div className="results-facts">
        <span><i>{L('Answered', '已回答')}</i>{answered} / {answers.length}</span>
        {job.summary && <span><i>{L('Time', '用时')}</i>{minutes(job.summary.wall_s, lang)}</span>}
        <span><i>{L('Cost', '费用')}</i>${(job.cost ?? 0).toFixed(3)}</span>
        <span><i>Workflow</i>{wfLabel(job.workflow, lang)}</span>
        <span><i>{L('Model', '模型')}</i>{job.profile}</span>
        {arxiv && <span><i>{L('Paper', '论文')}</i><a href={`https://arxiv.org/abs/${arxiv}`} target="_blank" rel="noreferrer">arXiv {arxiv}</a></span>}
      </div>
    </div>
    <div className="results-wrap">
      <table className="results-table">
        <colgroup><col className="c-id"/><col/><col className="c-num"/><col className="c-num"/><col className="c-num"/><col className="c-verdict"/></colgroup>
        <thead><tr><th>#</th><th>{L('Question', '问题')}</th><th>{L('Reproduced', '复现值')}</th><th>{refName}</th><th>{L('Gap', '差距')}</th><th>{L('Verdict', '结论')}</th></tr></thead>
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
              <details><summary>{L('Source, evidence and notes', '出处、证据和备注')}</summary>
                <dl>
                  {a.reference?.location && <><dt>{L(`${refName} value`, `${refName}中的值`)}</dt><dd>{a.reference.location}{a.reference.quote ? <q>{a.reference.quote}</q> : null}</dd></>}
                  {a.provenance && <><dt>{L('Answer source', '答案来源')}</dt><dd><span className={`prov is-${a.provenance.status}`}>{PROVENANCE[a.provenance.status] ? L(...PROVENANCE[a.provenance.status]) : a.provenance.status}</span></dd></>}
                  {a.evidence.length > 0 && <><dt>{L('Evidence', '证据')}</dt><dd>{a.evidence.map(e => <code key={e}>{e}</code>)}</dd></>}
                  {a.note && <><dt>{L('Agent’s note', 'Agent 的备注')}</dt><dd>{a.note}</dd></>}
                </dl>
              </details>
            </td></tr>,
          ];
        })}</tbody>
      </table>
    </div>
    {figures.length > 0 && <div className="results-figs">
      <div className="results-figs-head">{L('Figures this run made', '本次运行生成的图')}</div>
      <div className="results-figs-grid">{figures.map(p => IMAGE.test(p)
        ? <a key={p} href={api.fileUrl(jobKey, p)} target="_blank" rel="noreferrer" className="fig"><img src={api.fileUrl(jobKey, p)} alt={p}
          onError={e => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none'; }}/><span>{p}</span></a>
        : <a key={p} href={api.fileUrl(jobKey, p)} target="_blank" rel="noreferrer" className="fig is-file"><span>{L(`Open ${p}`, `打开 ${p}`)}</span></a>)}</div>
    </div>}
  </section>;
}

/* ---------------------------------------------------------------- chat messages */

function RunMessage({msg, job, wall, selectedId, onSelect, onStop}: {msg: Extract<Msg, {type: 'run'}>;
  job: JobState | null; wall: number; selectedId: string | null; onSelect: (id: string | null) => void; onStop: () => void}) {
  const {lang, L} = useLang();
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!full) return;
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setFull(false); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [full]);
  if (!job) return <div className="bubble"><span className="thinking"><Loader2 size={14} className="spin"/>{L('Starting…', '正在启动…')}</span></div>;
  const live = isLive(job);
  const c = current(job.nodes);
  const fallback = live ? job.nodes[0] : [...job.nodes].reverse().find(n => n.steps.length) ?? job.nodes[0];
  const selected = job.nodes.find(n => n.id === (selectedId ?? c?.node.id ?? fallback?.id)) ?? fallback;
  const outcome: RunOutcome = selected?.status === 'failed' ? 'error' : selected?.status === 'stopped' ? 'stopped' : 'done';
  const elapsed = job.summary && !live ? job.summary.wall_s : job.started ? Math.max(0, (wall - Date.parse(job.started)) / 1000) : 0;
  const provider = job.vendor ?? 'anthropic';
  let status: ReactNode;
  if (job.phase === 'queued') status = <><Clock size={13}/><span>{job.position === 1
    ? L(`Waiting in line: next to start (${job.running ?? 0} of ${job.max_running ?? '?'} slots busy). It starts by itself.`,
      `排队中：下一个就轮到你（${job.max_running ?? '?'} 个名额都在使用）。轮到时会自动开始。`)
    : L(`Waiting in line: ${(job.position ?? 1) - 1} ahead of you. It starts by itself.`,
      `排队中：前面还有 ${(job.position ?? 1) - 1} 个任务。轮到时会自动开始。`)}</span></>;
  else if (job.phase === 'preparing') status = <><Loader2 size={13} className="spin"/><span>{L('Preparing the workspace…', '正在准备工作目录…')}</span></>;
  else if (live && c) status = <><span className="now-live"/>{(() => { const I = ROLE_ICONS[c.node.kind]; return <I size={14}/>; })()}
    <span><b>{c.node.role}</b>{c.step ? <> · {c.step.label}{c.step.target ? <code>{c.step.target}</code> : null}</> : L(' · thinking…', ' · 思考中…')}</span></>;
  else if (live) status = <><Loader2 size={13} className="spin"/><span>{job.nodes[0]?.status === 'waiting'
    ? L(`${job.nodes[0].role} is waiting for its workers and commands…`, `${job.nodes[0].role} 正在等待 worker 和命令…`) : L('The agent is thinking…', 'Agent 正在思考…')}</span></>;
  else if (job.phase === 'done') status = <><Check size={13}/><span>{L('Finished. The results are below.', '已完成，结果在下方。')}</span></>;
  else status = <><X size={13}/><span>{job.phase === 'stopped' ? L('Stopped', '已停止') : `${L('The run failed', '运行失败')}${job.error ? `: ${job.error.slice(0, 200)}` : ''}`}</span></>;
  return <div className="bubble run-bubble">
    <p>{L(<>Reproducing “{job.spec?.title ?? ''}”. The window shows every agent and the step it is on; click a card to see all its steps.</>,
      <>正在复现“{job.spec?.title ?? ''}”。窗口里显示每个 agent 和它正在做的步骤；点击卡片可以查看它的全部步骤。</>)}</p>
    <div className={`run-window${full ? ' is-full' : ''}`}>
      <div className="run-window-head">
        <div className={`run-status is-${job.phase}`}>{status}</div>
        <div className="chips">
          <span className="chip">{wfLabel(job.workflow, lang)}</span>
          <span className="chip"><VendorLogo vendor={provider} size={12}/>{job.profile}</span>
          {job.spec?.code && <span className="chip">{job.spec.code.capsule ? <Package size={11}/> : <Github size={11}/>}{job.spec.code.capsule ?? job.spec.code.repo_url?.replace('https://github.com/', '')}</span>}
          <span className="chip clock">{minutes(elapsed, lang)}</span>
        </div>
        <div className="row">
          {live && <button type="button" className="btn ghost sm" onClick={onStop}><Square size={11}/>{L('Stop', '停止')}</button>}
          <button type="button" className="btn ghost sm" onClick={() => setFull(f => !f)} aria-label={full ? L('Exit full screen', '退出全屏') : L('Full screen', '全屏')}>
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
          <div className="side-label">{selectedId ? <>{L('Selected', '已选中')}: {selected.role}<button type="button" className="link" onClick={() => onSelect(null)}>{L('Follow current', '跟随当前')}</button></>
            : live ? L('Following the current agent', '正在跟随当前 agent') : L('Last agent at work', '最后工作的 agent')}</div>
          <AgentRun key={selected.id} steps={selected.steps} live={live && (selected.status === 'running' || selected.status === 'waiting')}
            outcome={outcome} badge={<Avatar provider={provider} kind={selected.kind}/>} iconFor={toolIcon}
            meta={<span>{selected.role}{selected.model ? ` · ${selected.model}` : ''}</span>}
            liveText={selected.status === 'waiting' ? L('Waiting for workers and commands…', '正在等待 worker 和命令…') : L('Thinking…', '思考中…')}
            extra={selected.summary ? <p className="side-summary">{selected.summary}</p> : undefined}/>
        </div>}
      </div>
    </div>
    {job.answers && <Results job={job} jobKey={msg.key}/>}
  </div>;
}

function SpecMessage({msg, onStart, busy, onRevealed, onGrow}: {msg: Extract<Msg, {type: 'spec'}>; onStart: () => void;
  busy: boolean; onRevealed: (id: number) => void; onGrow: () => void}) {
  const {L} = useLang();
  const {spec} = msg;
  const refName = msg.paper.source === 'corebench' ? L('Reference', '参考答案') : L('Paper', '论文');
  const tl = revealTimeline(spec, msg.paper);
  const [t, setT] = useState(() => msg.reveal && !reducedMotion() ? 0 : Infinity);  // ms since the card appeared
  useEffect(() => {
    if (t === Infinity) { onRevealed(msg.id); return; }
    const t0 = performance.now();
    let raf = 0;
    const frame = () => {
      const e = performance.now() - t0;
      if (e >= tl.end) { setT(Infinity); onRevealed(msg.id); return; }
      setT(e);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const revealing = t !== Infinity;
  useEffect(() => { if (revealing) onGrow(); });  // keep the growing card in view
  const typed = Math.max(0, Math.min(1, (t - tl.task) / tl.typeMs));
  const task = revealing ? spec.task_prompt.slice(0, Math.round(spec.task_prompt.length * typed)) : spec.task_prompt;
  let refIndex = 0;
  const intro = revealing ? <ShiningText text={L('Writing the plan…', '正在写计划…')}/>
    : <>{msg.cost ? L(`Here is your request as a task (drafting cost $${msg.cost.toFixed(4)}). `, `这是根据你的请求整理出的任务（起草花费 $${msg.cost.toFixed(4)}）。`)
        : L('Here is the example task. ', '这是示例任务。')}
      {msg.started ? L('It has started.', '已经开始运行。') : msg.example && busy ? L('Starting it…', '正在启动…')
        : L('Press Start or reply “start”; to change it, just say what to change.', '点“开始”或回复“开始”即可运行；想修改的话，直接说要改什么。')}</>;
  return <div className="bubble">
    <p>{intro}</p>
    <div className="spec-card">
      <div className="spec-head"><FlaskConical size={15}/><b>{spec.title}</b></div>
      {t >= tl.chips && <div className={`chips${revealing ? ' reveal-in' : ''}`}><span className="chip">{spec.code.capsule ? <><Package size={11}/>{spec.code.capsule}</> : <><Github size={11}/>{spec.code.repo_url?.replace('https://github.com/', '')}</>}</span>
        {spec.language && <span className="chip">{spec.language}</span>}</div>}
      {t >= tl.task && <p className={`spec-task${revealing && typed < 1 ? ' typing-caret' : ''}`}>{task}</p>}
      <ol className="spec-qs">{spec.questions.map((q, i) => {
        if (t < tl.q0 + i * tl.qStep) return null;
        const ref = msg.paper.values[q.id];
        const showRef = ref && t >= tl.r0 + (refIndex++) * tl.rStep;
        return <li key={q.id} className={revealing ? 'reveal-in' : undefined}><code>{q.id}</code>{q.text}<span className="muted"> · {q.answer_type}</span>
          {showRef && <div className={`paper-ref${revealing ? ' reveal-in' : ''}`}>{refName}: <b>{show(ref.value)}{ref.unit ? ` ${ref.unit}` : ''}</b>{ref.location ? <span className="muted"> ({ref.location})</span> : null}</div>}</li>;
      })}</ol>
      {t >= tl.note && <div className={`paper-note${revealing ? ' reveal-in' : ''}`}>{msg.paper.source === 'corebench'
        ? L(<>A CORE-Bench task: the answers are compared with its reference answers (the mean of 3 manual re-runs), which the agents never see.</>,
          <>CORE-Bench 任务：答案会和它的参考答案（3 次人工重跑的平均值）比较，agent 看不到这些参考答案。</>)
        : msg.paper.arxiv
          ? L(<>Paper <a href={`https://arxiv.org/abs/${msg.paper.arxiv}`} target="_blank" rel="noreferrer">arXiv {msg.paper.arxiv}</a>: found its value for {Object.keys(msg.paper.values).length} of {spec.questions.length} questions; the answers are compared with them at the end. The agents never see these values.</>,
            <>论文 <a href={`https://arxiv.org/abs/${msg.paper.arxiv}`} target="_blank" rel="noreferrer">arXiv {msg.paper.arxiv}</a>：{spec.questions.length} 个问题中找到了 {Object.keys(msg.paper.values).length} 个的论文值，最后会拿答案和它们比较。Agent 看不到这些值。</>)
          : L(<>No paper found (no arXiv link in the message or the README), so the answers cannot be compared. Add an arXiv link to the message to compare.</>,
            <>没有找到论文（消息和 README 里都没有 arXiv 链接），所以答案无法比较。在消息里加上 arXiv 链接就能比较。</>)}</div>}
    </div>
    {!msg.started && !revealing && !(msg.example && busy) && <div className="actions"><button type="button" className="btn primary sm" disabled={busy} onClick={onStart}>
      {busy ? <Loader2 size={14} className="spin"/> : <Play size={13}/>}{L('Start', '开始')}</button></div>}
  </div>;
}

/** The drafting steps of a plan, ticking off one by one; the last one stays at work until the plan arrives. */
function PlanSteps({steps, note}: {steps: string[]; note?: string}) {
  const {L} = useLang();
  const [at, setAt] = useState(0);
  useEffect(() => {
    if (at >= steps.length - 1) return;
    const t = setTimeout(() => setAt(a => a + 1), PLAN_STEP_MS);
    return () => clearTimeout(t);
  }, [at, steps.length]);
  return <div className="bubble">
    <div className="thinking-row"><Loader variant="newton" size={28}/><ShiningText text={L('Drafting the plan…', '正在起草计划…')}/></div>
    <ol className="plan-steps">{steps.slice(0, at + 1).map((s, i) => <li key={s} className={i < at ? 'is-done' : 'is-now'}>
      {i < at ? <Check size={13}/> : <Loader2 size={13} className="spin"/>}<span>{s}</span></li>)}</ol>
    {note && <p className="plan-note">{note}</p>}
  </div>;
}

function AskUrlMessage({msg, onSubmit}: {msg: Extract<Msg, {type: 'ask_url'}>; onSubmit: (url: string) => void}) {
  const {L} = useLang();
  const [url, setUrl] = useState('');
  const ok = GITHUB.test(url.trim());
  return <div className="bubble">
    <p>{L(<>Your request has no code to run. What is the <b>GitHub address</b> of the official code? The agents clone it and reproduce from there. Enter it below, or reply with it.</>,
      <>你的请求里没有可运行的代码。官方代码的 <b>GitHub 地址</b>是什么？Agent 会 clone 它并从那里开始复现。在下面填写，或者直接回复地址。</>)}</p>
    {!msg.resolved && <form className="url-form" onSubmit={e => { e.preventDefault(); if (ok) onSubmit(url.trim()); }}>
      <Github size={15}/><input className="input" placeholder="https://github.com/owner/repo" value={url} onChange={e => setUrl(e.target.value)} autoFocus/>
      <button type="submit" className="btn primary sm" disabled={!ok}>{L('Continue', '继续')}</button>
    </form>}
  </div>;
}

/* ---------------------------------------------------------------- app */

export function App() {
  const {lang, L} = useLang();
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
  // the server's "budget used up" message, in the page's language
  const why = useCallback((e: unknown) => {
    const m = (e as Error).message;
    const cap = /This month's API budget \(\$([\d.]+)\)/.exec(m);
    return cap ? L(m, `本月的 API 额度（$${cap[1]}）已经用完，下个月 1 日（UTC）重置。`) : m;
  }, [L]);
  const push = useCallback((m: NewMsg, by?: string) => {
    stick.current = true;
    const id = newId();
    setMsgs(ms => [...ms.filter(x => !(x.role === 'assistant' && x.type === 'thinking')), {...m, id, by: by ?? vendor} as Msg]);
    return id;
  }, [vendor]);
  // a plan card tells the app when it has finished appearing (the example waits for that before it starts the run)
  const revealWaiters = useRef(new Map<number, () => void>());
  const revealed = useCallback((id: number) => {
    revealWaiters.current.get(id)?.();
    revealWaiters.current.delete(id);
    setMsgs(ms => ms.map(m => m.id === id && m.role === 'assistant' && m.type === 'spec' && m.reveal ? {...m, reveal: false} : m));
  }, []);
  const untilRevealed = (id: number) => new Promise<void>(r => { revealWaiters.current.set(id, r); });
  const follow = useCallback(() => { const el = thread.current; if (el && stick.current) el.scrollTop = el.scrollHeight; }, []);
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
        else { refreshHistory(); api.examples().then(r => setExamples(r.examples), () => undefined); api.options().then(setOptions, () => undefined); }
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
      else push({role: 'assistant', type: 'spec', spec: r.spec, paper: r.paper, cost: r.cost, reveal: true});
    } catch (e) { push({role: 'assistant', type: 'text', text: `${L('Could not draft the task', '无法起草任务')}: ${why(e)}`}); }
    finally { setBusy(false); }
  }, [push, model, L, why]);

  const start = useCallback(async (mid: number, spec: Spec) => {
    setBusy(true);
    try {
      const r = await api.start({spec, workflow, model});
      patch(mid, m => ({...m, started: true} as Msg));
      open(r.key);
      refreshHistory();
    } catch (e) { push({role: 'assistant', type: 'text', text: `${L('Could not start', '无法启动')}: ${why(e)}`}); }
    finally { setBusy(false); }
  }, [workflow, model, patch, open, push, refreshHistory, L, why]);

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
      else push({role: 'assistant', type: 'text', text: L('I could not find a GitHub address in that. Please send a link like https://github.com/owner/repo.', '这条消息里没有找到 GitHub 地址。请发一个类似 https://github.com/owner/repo 的链接。')});
      return;
    }
    if (last?.role === 'assistant' && last.type === 'spec' && !last.started) {
      if (START_WORDS.test(text.trim())) { start(last.id, last.spec); return; }
      // a correction to the drafted task: draft it again with the correction
      draftSpec(`${last.spec.origin.prompt}\n${L('Also', '另外')}: ${text}`, url ?? last.spec.code.repo_url ?? undefined);
      return;
    }
    draftSpec(text, url);
  }, [msgs, push, resolveUrl, draftSpec, start, L]);

  // an example: the plan saved from the run that made it a good example, shown the way a plan is drafted (the steps,
  // then the card filling in), and started with the workflow and model chosen now once it is on screen
  const runExample = useCallback(async (e: ExampleTask) => {
    push({role: 'user', text: L(`Run the example “${e.title}” (${wfLabel(workflow, lang)} · ${model})`, `运行示例“${e.title}”（${wfLabel(workflow, lang)} · ${model}）`)});
    setBusy(true);
    const corebench = e.source === 'corebench';
    const code = /^https?:/.test(e.code) ? e.code.replace(/^https?:\/\/(www\.)?github\.com\//, '') : e.code;
    const steps = [L('Reading the request', '阅读请求'),
      corebench ? L(`Opening the CORE-Bench capsule ${code}`, `打开 CORE-Bench capsule ${code}`) : L(`Reading the repository ${code}`, `阅读代码仓库 ${code}`),
      L('Writing the task and its questions', '写出任务和要回答的问题'),
      corebench ? L('Loading CORE-Bench’s reference answers', '载入 CORE-Bench 的参考答案') : L('Looking up the values the paper reports', '查找论文报告的数值')];
    push({role: 'assistant', type: 'thinking', steps,
      note: L('This example’s plan was drafted when it was first run; it is replayed here, without a new model call.', '这个示例的计划是第一次运行时起草的，这里是重放，不会再调用模型。')});
    try {
      const [r] = await Promise.all([api.example(e.case), reducedMotion() ? null : sleep(steps.length * PLAN_STEP_MS)]);
      const mid = push({role: 'assistant', type: 'spec', spec: r.spec, paper: r.paper, cost: 0, example: true, reveal: true});
      await untilRevealed(mid);
      const r2 = await api.start({spec: r.spec, workflow, model});
      patch(mid, m => ({...m, started: true} as Msg));
      open(r2.key);
      refreshHistory();
    } catch (err) { push({role: 'assistant', type: 'text', text: `${L('Could not start', '无法启动')}: ${why(err)}`}); }
    finally { setBusy(false); }
  }, [push, patch, open, workflow, model, refreshHistory, L, lang, why]); // eslint-disable-line react-hooks/exhaustive-deps

  const stop = useCallback(() => { if (key) api.stop(key).catch(() => undefined); }, [key]);
  const lastRun = [...msgs].reverse().find(m => m.role === 'assistant' && m.type === 'run');

  return <div className={`app${page === 'changelog' ? ' is-changelog' : ''}`}>
    <TopBar dark={dark} onTheme={() => setDark(d => !d)}>
      <HistoryMenu runs={history} onRefresh={refreshHistory} onOpen={r => { leaveChangelog(); push({role: 'user', text: L(`Open “${r.title}”`, `打开“${r.title}”`)}); open(r.key); }}/>
      <button type="button" className={`menu-trigger${page === 'changelog' ? ' is-open' : ''}`} onClick={showChangelog}><ListChecks size={14}/><span>{L('Changelog', '更新日志')}</span></button>
    </TopBar>
    {page === 'changelog' && <ChangelogPage onBack={leaveChangelog}/>}
    {error && !options && <div className="error page-error">{L('Cannot reach the server', '无法连接服务器')}: {error} ({L('start it with', '用这条命令启动')} <code>p2e demo serve</code>)</div>}
    <main className={`layout${msgs.length ? '' : ' is-empty'}${page === 'changelog' ? ' is-hidden' : ''}`}>
      <section className="chat">
        {!msgs.length && <div className="hero">
          <h1>{L('What should we reproduce?', '想复现什么？')}</h1>
          <p>{L('Name the paper or code and the numbers or figures you want, ideally with the GitHub address. I’ll turn it into a task, run it with the workflow and model below, and compare the results with the paper.',
            '说出论文或代码，以及想复现的数字或图，最好附上 GitHub 地址。我会把它整理成任务，用下面选的 workflow 和模型运行，再把结果和论文对比。')}</p>
          <div className="suggest">{SUGGESTIONS[lang].map(x => <button type="button" key={x.label} className="suggest-btn" onClick={() => setDraft(x.text)}>{x.label}</button>)}</div>
        </div>}
        <div className="thread" ref={thread} onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
          {msgs.map(m => m.role === 'user'
            ? <div key={m.id} className="msg user"><div className="bubble">{m.text}</div></div>
            : <div key={m.id} className={`msg assistant${m.type === 'run' ? ' is-wide' : ''}`}>
              <Author vendor={m.type === 'run' && m.id === lastRun?.id && job?.vendor ? job.vendor : m.by}/>
              {m.type === 'thinking' && m.steps ? <PlanSteps steps={m.steps} note={m.note}/>
                : m.type === 'thinking' ? <div className="bubble"><div className="thinking-row"><Loader variant="newton" size={28}/><ShiningText text={L('Drafting the task and looking up the paper’s values…', '正在起草任务，并查找论文中的数值…')}/></div></div>
                : m.type === 'text' ? <div className="bubble"><p>{m.text}</p></div>
                : m.type === 'ask_url' ? <AskUrlMessage msg={m} onSubmit={u => { push({role: 'user', text: u}); resolveUrl(m.id, m.prompt, u); }}/>
                : m.type === 'spec' ? <SpecMessage msg={m} busy={busy} onStart={() => start(m.id, m.spec)} onRevealed={revealed} onGrow={follow}/>
                : m.id === lastRun?.id ? <RunMessage msg={m} job={job} wall={wall} selectedId={selectedId} onSelect={setSelectedId} onStop={stop}/>
                : <div className="bubble"><p className="muted">{L('An earlier run; open it again from History.', '较早的一次运行；可以从“历史记录”重新打开。')}</p></div>}
            </div>)}
        </div>
        {options && <Composer options={options} examples={examples} workdir={workdir} onWorkdir={setWorkdir} onSend={send}
          onExample={e => { if (!busy) runExample(e); }} busy={busy} onStop={isLive(job) ? stop : undefined}
          workflow={workflow} setWorkflow={setWorkflow} model={model} setModel={setModel} draft={draft} setDraft={setDraft}/>}
      </section>
    </main>
  </div>;
}
