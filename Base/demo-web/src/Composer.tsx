// The message box, in the shape of the reference composer: a white field on a grey tray. In the field: "+" (insert a
// repository or paper link), the workflow (where the reference has "Request approval"), Alex's model picker and send.
// On the tray: the run folder (where reproductions run) and the example tasks.
import {useEffect, useRef, useState, type ReactNode} from 'react';
import {ArrowUp, BookOpen, Check, FlaskConical, Github, Loader2, Package, Plus, Square} from 'lucide-react';
import {ModelPicker, type ModelPickerProvider} from './alex/modules/chat/components/ui/model-picker';
import {api} from './api';
import {ROLE_ICONS} from './icons';
import {VendorLogo} from './provider-logos';
import type {ExampleTask, ModelOption, Options, Workdir, Workflow} from './types';
import {useLang, type Lang} from './i18n';

// The three workflows' names and descriptions in both languages (the server sends English); unknown ids keep the server's.
const WF_TEXT: Record<string, {letter: string; name: [string, string]; desc: [string, string]}> = {
  single: {letter: 'A', name: ['Single agent', '单 agent'],
    desc: ['One agent does it all: sets up, runs the code, reads the output, answers', '一个 agent 包揽全部：搭环境、运行代码、读输出、回答问题']},
  fixed: {letter: 'B', name: ['Fixed pipeline', '固定 pipeline'],
    desc: ['A fixed pipeline: environment agent → planner → executor → answerer', '固定流程：环境 agent → planner → executor → answerer']},
  planner_workers: {letter: 'D', name: ['Planner + workers', 'Planner + workers'],
    desc: ['A planner hands out tasks as needed: workers set up, the runtime runs commands, failures are retried', '由 planner 按需分派任务：worker 搭环境，runtime 执行命令，失败的任务会重试']},
};
const pick = (pair: [string, string], lang: Lang) => pair[lang === 'zh' ? 1 : 0];
export const wfName = (w: Workflow, lang: Lang) => WF_TEXT[w.id] ? pick(WF_TEXT[w.id].name, lang) : w.name;
export const wfDesc = (w: Workflow, lang: Lang) => WF_TEXT[w.id] ? pick(WF_TEXT[w.id].desc, lang) : w.desc;
/** "D · Planner + workers": the letter and name of a workflow id, in the page's language. */
export const wfLabel = (id: string, lang: Lang) => WF_TEXT[id] ? `${WF_TEXT[id].letter} · ${pick(WF_TEXT[id].name, lang)}` : id;
export const VENDOR_NAME: Record<string, string> = {
  anthropic: 'Anthropic', openai: 'OpenAI', google: 'Google', xai: 'xAI', deepseek: 'DeepSeek', qwen: 'Qwen', kimi: 'Kimi',
  moonshot: 'Moonshot', zai: 'Z.ai', minimax: 'MiniMax', mistral: 'Mistral', meta: 'Meta', openrouter: 'OpenRouter', groq: 'Groq',
};
const BUILT_IN_GLYPHS = new Set(['anthropic', 'openai', 'google', 'xai']);  // Alex's ProviderGlyph draws these itself

const minutes = (s: number, lang: Lang) => s < 60 ? `${Math.round(s)} ${lang === 'zh' ? '秒' : 's'}`
  : `${(s / 60).toFixed(s < 600 ? 1 : 0)} ${lang === 'zh' ? '分钟' : 'min'}`;

/** "claude-haiku-5-5" -> "Claude Haiku 5.5", "gpt-6-luna" -> "GPT-6 Luna" */
function modelName(id: string) {
  return id.replace(/^gpt-/, 'GPT-').replace(/-(\d+)-(\d+)$/, ' $1.$2').split('-')
    .map(w => /^GPT/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)).join(' ').replace(/^GPT (\d)/, 'GPT-$1');
}

/** The demo's model profiles as Alex's picker wants them: one rail per vendor, its logo, the profiles with a key. */
export function pickerProviders(models: ModelOption[]): ModelPickerProvider[] {
  const byVendor = new Map<string, ModelOption[]>();
  for (const m of models) byVendor.set(m.vendor, [...(byVendor.get(m.vendor) ?? []), m]);
  return [...byVendor].map(([vendor, ms]) => ({
    id: vendor, name: VENDOR_NAME[vendor] ?? vendor,
    icon: BUILT_IN_GLYPHS.has(vendor) ? undefined : <VendorLogo vendor={vendor} size={16}/>,
    models: ms.map(m => ({id: m.id, name: modelName(m.model), description: `${m.id} · ${m.model}`, available: m.available})),
  }));
}

/** A small popover anchored to its trigger, opening upwards; closes on an outside click or Escape. */
function Popup({trigger, align = 'left', children}: {trigger: (open: boolean, toggle: () => void) => ReactNode; align?: 'left' | 'right';
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
  return <div className="popup" ref={ref}>
    {trigger(open, () => setOpen(o => !o))}
    {open && <div className={`popup-panel is-${align}`} role="menu">{children(() => setOpen(false))}</div>}
  </div>;
}

function FolderGlyph() {
  return <svg className="folder-glyph" width="22" height="18" viewBox="0 0 22 18" aria-hidden="true">
    <defs><linearGradient id="fg-back" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4f9cf7"/><stop offset="1" stopColor="#3a86ec"/></linearGradient>
      <linearGradient id="fg-front" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#8fd0ff"/><stop offset="1" stopColor="#62b6fb"/></linearGradient></defs>
    <path d="M1 3.2C1 2 2 1 3.2 1h4.6c.6 0 1.1.2 1.5.6l1.3 1.3c.4.4.9.6 1.5.6h6.7C20 3.5 21 4.5 21 5.7v9.1c0 1.2-1 2.2-2.2 2.2H3.2C2 17 1 16 1 14.8V3.2Z" fill="url(#fg-back)"/>
    <path d="M1 6.6c0-1.2 1-2.2 2.2-2.2h15.6c1.2 0 2.2 1 2.2 2.2v8.2c0 1.2-1 2.2-2.2 2.2H3.2C2 17 1 16 1 14.8V6.6Z" fill="url(#fg-front)"/>
  </svg>;
}

function RunFolder({workdir, onChange}: {workdir: Workdir | null; onChange: (w: Workdir) => void}) {
  const {L} = useLang();
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (f: () => Promise<Workdir & {cancelled?: boolean}>, close: () => void) => {
    setBusy(true); setError('');
    try { const w = await f(); if (!w.cancelled) { onChange(w); close(); } }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <Popup trigger={(open, toggle) => <button type="button" className={`tray-btn${open ? ' is-open' : ''}`} onClick={toggle}
    title={workdir?.path}><FolderGlyph/><span>{workdir?.chosen ? workdir.name : L('Run in a folder', '选择运行目录')}</span></button>}>
    {close => <div className="folder-panel">
      <div className="popup-head">{L('Run folder', '运行目录')}</div>
      <p className="popup-text">{L('Each reproduction gets its own sub-folder here: the cloned code, its environment and everything it writes.', '每次复现都会在这里建一个子目录，存放 clone 下来的代码、它的环境和它写出的所有文件。')}</p>
      <code className="folder-path">{workdir?.path ?? '…'}</code>
      <button type="button" className="btn primary sm wide" disabled={busy} onClick={() => act(api.chooseWorkdir, close)}>
        {busy ? <Loader2 size={13} className="spin"/> : <FolderGlyph/>}{L('Choose a folder…', '选择文件夹…')}</button>
      <form className="folder-form" onSubmit={e => { e.preventDefault(); if (path.trim()) act(() => api.setWorkdir(path.trim()), close); }}>
        <input className="input" placeholder={L('or paste a path, e.g. ~/reproductions', '或者粘贴路径，例如 ~/reproductions')} value={path} onChange={e => setPath(e.target.value)}/>
        <button type="submit" className="btn ghost sm" disabled={busy || !path.trim()}>{L('Use', '使用')}</button>
      </form>
      {workdir?.chosen && <button type="button" className="link" onClick={() => act(() => api.setWorkdir(workdir.default), close)}>{L('Back to the default', '恢复默认')} ({workdir.default})</button>}
      {error && <div className="error">{error}</div>}
    </div>}
  </Popup>;
}

/** How long an example takes: what its runs took on the demo server (a range when they differ by a minute or more),
 * else the fastest earlier run. */
function exampleTime(e: ExampleTask, lang: Lang) {
  const s = e.demo_s;
  if (!s?.length) return minutes(e.fastest_s, lang);
  const lo = Math.min(...s), hi = Math.max(...s);
  if (hi - lo < 60) return minutes(s.reduce((a, b) => a + b, 0) / s.length, lang);
  return `${Math.round(lo / 60)}–${Math.round(hi / 60)} ${lang === 'zh' ? '分钟' : 'min'}`;
}

function ExampleTasks({examples, workflow, model, onPick}: {examples: ExampleTask[] | null; workflow: string; model: string; onPick: (e: ExampleTask) => void}) {
  const {lang, L} = useLang();
  return <Popup align="right" trigger={(open, toggle) => <button type="button" className={`tray-btn${open ? ' is-open' : ''}`} onClick={toggle}>
    <span>{L('Example tasks', '示例任务')}</span>
    <span className="tray-marks" aria-hidden="true">
      <span className="mark is-flask"><FlaskConical size={11} strokeWidth={2.4}/></span>
      <span className="mark is-github"><Github size={11} strokeWidth={2.4}/></span>
      <span className="mark is-package"><Package size={11} strokeWidth={2.4}/></span>
    </span></button>}>
    {close => <div className="examples-panel">
      <div className="popup-head">{L('Example tasks', '示例任务')}</div>
      <p className="popup-text">{examples?.some(e => e.demo_s)
        ? L(<>{examples.length} tasks that ran through on this server; the time is what they took here. Pick one to run it from scratch with <b>{wfLabel(workflow, lang)} · {model}</b>.</>,
          <>在这台服务器上实测跑通的 {examples.length} 个任务，右边是在这里的实际用时。选一个，会用 <b>{wfLabel(workflow, lang)} · {model}</b> 从头运行。</>)
        : L(<>{examples?.length ?? '…'} tasks an earlier run answered in under 10 minutes. Pick one to run it from scratch with <b>{wfLabel(workflow, lang)} · {model}</b>.</>,
          <>以前的运行在 10 分钟内答完的 {examples?.length ?? '…'} 个任务。选一个，会用 <b>{wfLabel(workflow, lang)} · {model}</b> 从头运行。</>)}</p>
      <div className="popup-scroll">
        {!examples ? <div className="popup-empty"><Loader2 size={14} className="spin"/></div>
          : !examples.length ? <div className="popup-empty">{L('No quick tasks yet', '还没有能快速跑完的任务')}</div>
          : examples.map(e => <button type="button" key={e.case} role="menuitem" className="popup-item" onClick={() => { close(); onPick(e); }}>
            <span className="popup-icon">{e.code.startsWith('http') ? <Github size={14}/> : <Package size={14}/>}</span>
            <span className="popup-main"><b>{e.title}</b>
              <small>{e.code.replace('https://github.com/', '')}{e.language ? ` · ${e.language}` : ''} · {L(`${e.questions} ${e.questions === 1 ? 'question' : 'questions'}`, `${e.questions} 个问题`)}</small></span>
            <span className="popup-meta">{exampleTime(e, lang)}</span>
          </button>)}
      </div>
    </div>}
  </Popup>;
}

function WorkflowPicker({options, value, onChange}: {options: Options; value: string; onChange: (id: string) => void}) {
  const {lang, L} = useLang();
  const w = options.workflows.find(x => x.id === value);
  const iconOf = (id: string) => ROLE_ICONS[id === 'single' ? 'agent' : id === 'fixed' ? 'pipeline' : 'planner'];
  const Icon = iconOf(value);
  return <Popup trigger={(open, toggle) => <button type="button" className={`flat-btn${open ? ' is-open' : ''}`} onClick={toggle} title={w ? wfDesc(w, lang) : undefined}>
    <Icon size={19} strokeWidth={1.6}/><span>{w ? wfName(w, lang) : 'Workflow'}</span></button>}>
    {close => <div className="workflow-panel">
      <div className="popup-head">Workflow</div>
      {options.workflows.map(x => {
        const I = iconOf(x.id);
        return <button type="button" key={x.id} role="menuitemradio" aria-checked={x.id === value} className={`popup-item${x.id === value ? ' is-on' : ''}`}
          onClick={() => { onChange(x.id); close(); }}>
          <span className="popup-icon"><I size={15}/></span>
          <span className="popup-main"><b>{x.letter} · {wfName(x, lang)}</b><small>{wfDesc(x, lang)}</small></span>
          {x.id === value && <Check size={14} className="popup-check"/>}
        </button>;
      })}
    </div>}
  </Popup>;
}

export function Composer({options, examples, workdir, onWorkdir, onSend, onExample, busy, onStop, workflow, setWorkflow, model, setModel,
  draft, setDraft}: {
  options: Options; examples: ExampleTask[] | null; workdir: Workdir | null; onWorkdir: (w: Workdir) => void;
  onSend: (text: string) => void; onExample: (e: ExampleTask) => void; busy: boolean; onStop?: () => void;
  workflow: string; setWorkflow: (w: string) => void; model: string; setModel: (m: string) => void;
  draft: string; setDraft: (t: string) => void;
}) {
  const {L} = useLang();
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { const el = ref.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(220, Math.max(64, el.scrollHeight))}px`; } }, [draft]);
  const send = () => { const t = draft.trim(); if (t && !busy) { onSend(t); setDraft(''); } };
  const insert = (text: string) => {
    setDraft(draft.trim() ? `${draft.trimEnd()}\n${text}` : text);
    requestAnimationFrame(() => { const el = ref.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } });
  };
  return <div className="composer">
    <div className="composer-field">
      <textarea ref={ref} rows={2} value={draft} placeholder={L('Start by typing… e.g. reproduce Table 2 of the paper at https://github.com/…', '输入你的请求… 例如：复现 https://github.com/… 这篇论文的表 2')}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/>
      <div className="composer-row">
        <Popup trigger={(open, toggle) => <button type="button" className={`icon-flat${open ? ' is-open' : ''}`} onClick={toggle} aria-label={L('Add a link', '添加链接')}>
          <Plus size={20} strokeWidth={1.6}/></button>}>
          {close => <div className="plus-panel">
            <button type="button" className="popup-item" onClick={() => { insert(`${L('Code', '代码')}: https://github.com/`); close(); }}>
              <span className="popup-icon"><Github size={14}/></span><span className="popup-main"><b>{L('GitHub repository', 'GitHub 仓库')}</b><small>{L('The code to reproduce with', '用来复现的代码')}</small></span></button>
            <button type="button" className="popup-item" onClick={() => { insert(`${L('Paper', '论文')}: https://arxiv.org/abs/`); close(); }}>
              <span className="popup-icon"><BookOpen size={14}/></span><span className="popup-main"><b>{L('arXiv paper', 'arXiv 论文')}</b><small>{L('Its numbers are what the answers are compared with', '答案会和论文里的数字比较')}</small></span></button>
          </div>}
        </Popup>
        <WorkflowPicker options={options} value={workflow} onChange={setWorkflow}/>
        <span className="composer-spacer"/>
        <ModelPicker compact promptStyle providers={pickerProviders(options.models)} value={model} placeholder={L('No model configured', '没有配置模型')}
          onValueChange={id => setModel(id)} side="top" align="end" className="min-w-0 max-w-[220px] text-[15px]"/>
        {onStop
          ? <button type="button" className="send-btn is-stop" onClick={onStop} aria-label={L('Stop the run', '停止运行')}><Square size={13} fill="currentColor"/></button>
          : <button type="button" className="send-btn" disabled={!draft.trim() || busy} onClick={send} aria-label={L('Send', '发送')}><ArrowUp size={19} strokeWidth={2}/></button>}
      </div>
    </div>
    <div className="composer-tray">
      <RunFolder workdir={workdir} onChange={onWorkdir}/>
      {options.budget?.limit_usd != null && <span className={`tray-budget${options.budget.exhausted ? ' is-out' : ''}`}
        title={L('LLM spend of this demo this month (UTC); runs stop when it reaches the cap', '本 demo 本月（UTC）的 LLM 花费；达到上限后不再运行')}>
        {L('This month', '本月')} ${options.budget.spent_usd.toFixed(2)} / ${options.budget.limit_usd.toFixed(0)}</span>}
      <ExampleTasks examples={examples} workflow={workflow} model={model} onPick={onExample}/>
    </div>
  </div>;
}

