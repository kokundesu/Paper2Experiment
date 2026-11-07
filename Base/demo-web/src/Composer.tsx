// The message box, in the shape of the reference composer: a white field on a grey tray. In the field: "+" (insert a
// repository or paper link), the workflow (where the reference has "Request approval"), Alex's model picker and send.
// On the tray: the run folder (where reproductions run) and the example tasks.
import {useEffect, useRef, useState, type ReactNode} from 'react';
import {ArrowUp, BookOpen, Check, FlaskConical, Github, Loader2, Package, Plus, Square} from 'lucide-react';
import {ModelPicker, type ModelPickerProvider} from './alex/modules/chat/components/ui/model-picker';
import {api} from './api';
import {ROLE_ICONS} from './icons';
import {VendorLogo} from './provider-logos';
import type {ExampleTask, ModelOption, Options, Workdir} from './types';

export const WF_LABEL: Record<string, string> = {single: 'A · Single agent', fixed: 'B · Fixed pipeline', planner_workers: 'D · Planner + workers'};
export const VENDOR_NAME: Record<string, string> = {
  anthropic: 'Anthropic', openai: 'OpenAI', google: 'Google', xai: 'xAI', deepseek: 'DeepSeek', qwen: 'Qwen', kimi: 'Kimi',
  moonshot: 'Moonshot', zai: 'Z.ai', minimax: 'MiniMax', mistral: 'Mistral', meta: 'Meta', openrouter: 'OpenRouter', groq: 'Groq',
};
const BUILT_IN_GLYPHS = new Set(['anthropic', 'openai', 'google', 'xai']);  // Alex's ProviderGlyph draws these itself

const minutes = (s: number) => s < 60 ? `${Math.round(s)} s` : `${(s / 60).toFixed(s < 600 ? 1 : 0)} min`;

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
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (f: () => Promise<Workdir & {cancelled?: boolean}>, close: () => void) => {
    setBusy(true); setError('');
    try { const w = await f(); if (!w.cancelled) { onChange(w); close(); } }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <Popup trigger={(open, toggle) => <button type="button" className={`tray-btn${open ? ' is-open' : ''}`} onClick={toggle}
    title={workdir?.path}><FolderGlyph/><span>{workdir?.chosen ? workdir.name : 'Run in a folder'}</span></button>}>
    {close => <div className="folder-panel">
      <div className="popup-head">Run folder</div>
      <p className="popup-text">Each reproduction gets its own sub-folder here: the cloned code, its environment and everything it writes.</p>
      <code className="folder-path">{workdir?.path ?? '…'}</code>
      <button type="button" className="btn primary sm wide" disabled={busy} onClick={() => act(api.chooseWorkdir, close)}>
        {busy ? <Loader2 size={13} className="spin"/> : <FolderGlyph/>}Choose a folder…</button>
      <form className="folder-form" onSubmit={e => { e.preventDefault(); if (path.trim()) act(() => api.setWorkdir(path.trim()), close); }}>
        <input className="input" placeholder="or paste a path, e.g. ~/reproductions" value={path} onChange={e => setPath(e.target.value)}/>
        <button type="submit" className="btn ghost sm" disabled={busy || !path.trim()}>Use</button>
      </form>
      {workdir?.chosen && <button type="button" className="link" onClick={() => act(() => api.setWorkdir(workdir.default), close)}>Back to the default ({workdir.default})</button>}
      {error && <div className="error">{error}</div>}
    </div>}
  </Popup>;
}

function ExampleTasks({examples, workflow, model, onPick}: {examples: ExampleTask[] | null; workflow: string; model: string; onPick: (e: ExampleTask) => void}) {
  return <Popup align="right" trigger={(open, toggle) => <button type="button" className={`tray-btn${open ? ' is-open' : ''}`} onClick={toggle}>
    <span>Example tasks</span>
    <span className="tray-marks" aria-hidden="true">
      <span className="mark is-flask"><FlaskConical size={11} strokeWidth={2.4}/></span>
      <span className="mark is-github"><Github size={11} strokeWidth={2.4}/></span>
      <span className="mark is-package"><Package size={11} strokeWidth={2.4}/></span>
    </span></button>}>
    {close => <div className="examples-panel">
      <div className="popup-head">Example tasks</div>
      <p className="popup-text">{examples?.length ?? '…'} tasks an earlier run answered in under 10 minutes. Pick one to run it from scratch with <b>{WF_LABEL[workflow]} · {model}</b>.</p>
      <div className="popup-scroll">
        {!examples ? <div className="popup-empty"><Loader2 size={14} className="spin"/></div>
          : !examples.length ? <div className="popup-empty">No quick tasks yet</div>
          : examples.map(e => <button type="button" key={e.case} role="menuitem" className="popup-item" onClick={() => { close(); onPick(e); }}>
            <span className="popup-icon">{e.code.startsWith('http') ? <Github size={14}/> : <Package size={14}/>}</span>
            <span className="popup-main"><b>{e.title}</b>
              <small>{e.code.replace('https://github.com/', '')}{e.language ? ` · ${e.language}` : ''} · {e.questions} {e.questions === 1 ? 'question' : 'questions'}</small></span>
            <span className="popup-meta">{minutes(e.fastest_s)}</span>
          </button>)}
      </div>
    </div>}
  </Popup>;
}

function WorkflowPicker({options, value, onChange}: {options: Options; value: string; onChange: (id: string) => void}) {
  const w = options.workflows.find(x => x.id === value);
  const iconOf = (id: string) => ROLE_ICONS[id === 'single' ? 'agent' : id === 'fixed' ? 'pipeline' : 'planner'];
  const Icon = iconOf(value);
  return <Popup trigger={(open, toggle) => <button type="button" className={`flat-btn${open ? ' is-open' : ''}`} onClick={toggle} title={w?.desc}>
    <Icon size={19} strokeWidth={1.6}/><span>{w ? w.name : 'Workflow'}</span></button>}>
    {close => <div className="workflow-panel">
      <div className="popup-head">Workflow</div>
      {options.workflows.map(x => {
        const I = iconOf(x.id);
        return <button type="button" key={x.id} role="menuitemradio" aria-checked={x.id === value} className={`popup-item${x.id === value ? ' is-on' : ''}`}
          onClick={() => { onChange(x.id); close(); }}>
          <span className="popup-icon"><I size={15}/></span>
          <span className="popup-main"><b>{x.letter} · {x.name}</b><small>{x.desc}</small></span>
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
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { const el = ref.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(220, Math.max(64, el.scrollHeight))}px`; } }, [draft]);
  const send = () => { const t = draft.trim(); if (t && !busy) { onSend(t); setDraft(''); } };
  const insert = (text: string) => {
    setDraft(draft.trim() ? `${draft.trimEnd()}\n${text}` : text);
    requestAnimationFrame(() => { const el = ref.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } });
  };
  return <div className="composer">
    <div className="composer-field">
      <textarea ref={ref} rows={2} value={draft} placeholder="Start by typing… e.g. reproduce Table 2 of the paper at https://github.com/…"
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/>
      <div className="composer-row">
        <Popup trigger={(open, toggle) => <button type="button" className={`icon-flat${open ? ' is-open' : ''}`} onClick={toggle} aria-label="Add a link">
          <Plus size={20} strokeWidth={1.6}/></button>}>
          {close => <div className="plus-panel">
            <button type="button" className="popup-item" onClick={() => { insert('Code: https://github.com/'); close(); }}>
              <span className="popup-icon"><Github size={14}/></span><span className="popup-main"><b>GitHub repository</b><small>The code to reproduce with</small></span></button>
            <button type="button" className="popup-item" onClick={() => { insert('Paper: https://arxiv.org/abs/'); close(); }}>
              <span className="popup-icon"><BookOpen size={14}/></span><span className="popup-main"><b>arXiv paper</b><small>Its numbers are what the answers are compared with</small></span></button>
          </div>}
        </Popup>
        <WorkflowPicker options={options} value={workflow} onChange={setWorkflow}/>
        <span className="composer-spacer"/>
        <ModelPicker compact promptStyle providers={pickerProviders(options.models)} value={model} placeholder="No model configured"
          onValueChange={id => setModel(id)} side="top" align="end" className="min-w-0 max-w-[220px] text-[15px]"/>
        {onStop
          ? <button type="button" className="send-btn is-stop" onClick={onStop} aria-label="Stop the run"><Square size={13} fill="currentColor"/></button>
          : <button type="button" className="send-btn" disabled={!draft.trim() || busy} onClick={send} aria-label="Send"><ArrowUp size={19} strokeWidth={2}/></button>}
      </div>
    </div>
    <div className="composer-tray">
      <RunFolder workdir={workdir} onChange={onWorkdir}/>
      <ExampleTasks examples={examples} workflow={workflow} model={model} onPick={onExample}/>
    </div>
  </div>;
}

