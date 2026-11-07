// Alex_Pi：对话里 agent 的运行面板（2026-10-25 用户给的 agent-run-widget.html 定稿）。
// 跑的时候展开成卡片：左上状态徽标（转圈 / 等批准的蓝点 / 完成的绿勾）+ 当前这一步（换步时上下滑动切换）+ 计时；
// 下面是分段进度条和最近 5 步的滚动列表，悬停（触屏点一下）某一步看详情。跑完收成一颗胶囊，点开再看。
// 对话助手的工具调用和 Alex 的委托都用它；某一步要批准时，审批（说明、详情、批准 / 拒绝按钮）就在面板里，不再单独一张卡片。
// 2026-10-25 用户：跑完不再自动收成胶囊（默认展开，点标题可以收起）；徽标中间是这次回复用的模型的图标。
import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {AnimatePresence, motion, useReducedMotion} from 'motion/react';
import {HoverCard} from 'radix-ui';
import {Check, ChevronDown, Square, X} from 'lucide-react';
// Paper2Exp demo: copied from Alex (apps/web/src/modules/chat/components/ui/agent-run.tsx); ToolStatus is @alex/shared's,
// and the visible text is in English (the demo's language); the structure and behaviour are unchanged.
export type ToolStatus = 'running' | 'awaiting_approval' | 'done' | 'error' | 'denied';
import './agent-run.css';

export type RunStep = {
 id: string;
 name: string;
 label: string;
 target?: string;
 status: ToolStatus;
 summary?: string;
 startedAt?: string;
 finishedAt?: string;
 args?: Record<string, unknown>;
 savedNote?: {id: string; title?: string};
};
/** 面板里的审批：某一步执行前要用户批准 */
export type RunApproval = {
 title: string;
 description: string;
 details: {label: string; value: string}[];
 /** 第一个是主按钮（批准） */
 actions: {label: string; value: string}[];
 busy?: boolean;
 onAction: (value: string) => void;
};

/** 结束后的结果：done 正常结束；error 出错；stopped 用户停止；partial 只做了一部分；denied 有操作被拒绝 */
export type RunOutcome = 'done' | 'error' | 'stopped' | 'partial' | 'denied';

const MAX_ROWS = 5;
const MAX_SEGMENTS = 12;
const STATUS_TEXT: Record<ToolStatus, string> = {running: 'Running', awaiting_approval: 'Awaiting approval', done: 'Done', error: 'Error', denied: 'Denied / stopped'};

const ms = (iso?: string) => (iso ? new Date(iso).getTime() : NaN);
/** 总计时：m:ss */
function clock(seconds: number) {
 const s = Math.max(0, Math.floor(seconds));
 const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
 return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}
/** 一步用时：1.9s / 12s / 1m 03s */
function span(seconds: number) {
 if (!Number.isFinite(seconds) || seconds < 0) return '';
 if (seconds < .05) return '<0.1s';
 if (seconds < 10) return `${seconds.toFixed(1)}s`;
 if (seconds < 60) return `${Math.round(seconds)}s`;
 const m = Math.floor(seconds / 60), r = Math.round(seconds % 60);
 return `${m}m ${String(r).padStart(2, '0')}s`;
}
const stepText = (s: RunStep) => `${s.label}${s.target ? ` · ${s.target}` : ''}`;
const isLive = (s: RunStep) => s.status === 'running' || s.status === 'awaiting_approval';

/** 参数的一行：字符串原样（截短），其余转 JSON */
function argValue(v: unknown) {
 const text = typeof v === 'string' ? v : JSON.stringify(v) ?? '';
 return text.length > 280 ? `${text.slice(0, 280)}…` : text;
}

function ApprovalBox({approval}: {approval: RunApproval}) {
 const [open, setOpen] = useState(false);
 return <div className="arp-approval" onClick={e => e.stopPropagation()}>
  <div className="arp-approval-title">{approval.title}</div>
  {approval.description && <p className="arp-approval-desc">{approval.description}</p>}
  {approval.details.length > 0 && <>
   <button type="button" className="arp-approval-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}>Details<ChevronDown size={12} className={open ? 'is-open' : ''}/></button>
   {open && <dl className="arp-approval-details">{approval.details.map((d, i) => <div key={i}><dt>{d.label}</dt><dd>{d.value}</dd></div>)}</dl>}
  </>}
  <div className="arp-approval-actions">{approval.actions.map((a, i) => <button key={a.value} type="button" className={`arp-btn${i === 0 ? ' is-approve' : ''}`} disabled={approval.busy} onClick={() => approval.onAction(a.value)}>
   {i === 0 ? <Check size={12} strokeWidth={2.4}/> : a.value === 'deny' ? <X size={11} strokeWidth={2.2}/> : null}{a.label}
  </button>)}</div>
 </div>;
}

export function AgentRun({steps, live, outcome = 'done', badge, meta, iconFor, onStop, onOpenNote, extra, footer, liveText, className, approval}: {
 steps: RunStep[];
 /** 还在跑（这条回复在生成、这一段是最新的） */
 live: boolean;
 outcome?: RunOutcome;
 /** 徽标中间的图标：对话助手是星芒，Alex 是它的小脸 */
 badge: ReactNode;
 /** 第二行左边：模型名 / Alex 的名字和任务 */
 meta?: ReactNode;
 iconFor: (name: string) => ReactNode;
 onStop?: () => void;
 onOpenNote?: (id: string, title?: string) => void;
 /** 正在做什么（没有在跑的那一步时显示，例如「正在思考…」） */
 liveText?: string;
 /** 步骤列表下面的内容（Alex 的报告） */
 extra?: ReactNode;
 /** 底栏右边的按钮（屏幕、账本下载） */
 footer?: ReactNode;
 className?: string;
 /** 正在等批准的那一步的审批（在面板里批） */
 approval?: RunApproval;
}) {
 const reduce = useReducedMotion();
 // 默认展开（跑完也不自动收起），点标题收成胶囊；又跑起来或有审批时自动展开
 const [collapsed, setCollapsed] = useState(false);
 useEffect(() => { if (live || approval) setCollapsed(false); }, [live, !!approval]); // eslint-disable-line react-hooks/exhaustive-deps
 // 跑的时候每半秒刷一次计时
 const [now, setNow] = useState(Date.now());
 useEffect(() => { if (!live) return; const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, [live]);

 const current = [...steps].reverse().find(isLive);
 const waiting = steps.find(s => s.status === 'awaiting_approval');
 const doneCount = steps.filter(s => !isLive(s)).length;
 const failed = steps.filter(s => s.status === 'error').length;
 const starts = steps.map(s => ms(s.startedAt)).filter(Number.isFinite);
 const ends = steps.map(s => ms(s.finishedAt)).filter(Number.isFinite);
 const t0 = starts.length ? Math.min(...starts) : NaN;
 const t1 = live ? now : ends.length ? Math.max(...ends) : NaN;
 const total = Number.isFinite(t0) && Number.isFinite(t1) ? (t1 - t0) / 1000 : NaN;

 const state = live ? (waiting ? 'approval' : 'running') : outcome === 'done' || outcome === 'partial' ? 'done' : 'failed';
 const title = live
  ? waiting ? {key: `wait-${waiting.id}`, icon: waiting.name, text: `Awaiting approval: ${stepText(waiting)}`, primary: true}
   : current ? {key: `run-${current.id}`, icon: current.name, text: stepText(current), primary: false}
   : {key: 'think', icon: '', text: liveText ?? 'Thinking…', primary: false}
  : {key: `end-${outcome}`, icon: '', primary: true, text: [
   outcome === 'stopped' ? 'Stopped' : outcome === 'error' ? 'Error' : outcome === 'partial' ? 'Partly done' : outcome === 'denied' ? 'An action was denied' : 'Done',
   `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`,
   ...(Number.isFinite(total) && total >= 1 ? [`took ${span(total)}`] : []),
   ...(failed && outcome === 'done' ? [`${failed} failed`] : []),
  ].join(' · ')};

 // 列表：跑的时候新的一步出现就滚到最下面；用户往上翻过就不再跟
 const listRef = useRef<HTMLDivElement>(null);
 const follow = useRef(true);
 useEffect(() => { const el = listRef.current; if (el && follow.current) el.scrollTop = el.scrollHeight; }, [steps.length, collapsed]);
 const [openRow, setOpenRow] = useState<string | null>(null);
 // 窄的地方（右侧栏里的对话只有 300–400 宽）右边放不下详情框，左右都放不下时 Radix 不会挪回来、框跑到窗口外：改放在这一步下面
 const narrow = window.innerWidth < 720;

 const segments = useMemo(() => {
  const n = Math.min(steps.length, MAX_SEGMENTS);
  const per = Math.ceil(steps.length / Math.max(1, n));
  return Array.from({length: n}, (_, i) => {
   const group = steps.slice(i * per, (i + 1) * per);
   const done = group.filter(s => !isLive(s)).length;
   return {fill: group.length ? done / group.length : 0, running: group.some(isLive), failed: group.some(s => s.status === 'error')};
  });
 }, [steps]);

 return <section className={`arp is-${state}${collapsed ? ' is-collapsed' : ''}${className ? ` ${className}` : ''}`} aria-label="Run"
  onClick={collapsed ? () => setCollapsed(false) : undefined} role={collapsed ? 'button' : undefined} tabIndex={collapsed ? 0 : undefined}
  onKeyDown={collapsed ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setCollapsed(false); } } : undefined}>
  <header className="arp-head" title={collapsed ? undefined : live ? undefined : 'Click to collapse'} onClick={collapsed ? undefined : () => { if (!live && !approval) setCollapsed(true); }}>
   <span className="arp-badge">
    <svg className="arp-ring" viewBox="0 0 24 24" aria-hidden><circle className="arp-ring-track" cx="12" cy="12" r="10.5"/><circle className="arp-ring-spin" cx="12" cy="12" r="10.5"/></svg>
    <span className="arp-badge-icon">{badge}</span>
    <i className="arp-dot" aria-hidden/>
    <span className="arp-check" aria-hidden>{state === 'failed' ? <X size={11} strokeWidth={2.4}/> : <Check size={11} strokeWidth={2.6}/>}</span>
   </span>
   <span className="arp-title" title={title.text}>
    <AnimatePresence initial={false} mode="popLayout">
     <motion.span key={title.key} className={`arp-title-item${title.primary ? ' is-primary' : ''}`}
      initial={reduce ? false : {y: 15, opacity: 0}} animate={{y: 0, opacity: 1}} exit={reduce ? {opacity: 0} : {y: -15, opacity: 0}}
      transition={{duration: .34, ease: [.22, 1, .36, 1]}}>
      {title.icon && <span className="arp-title-icon">{iconFor(title.icon)}</span>}
      <span className={title.primary ? 'arp-title-text' : 'arp-title-text arp-shimmer'}>{title.text}</span>
     </motion.span>
    </AnimatePresence>
   </span>
   {live && Number.isFinite(total) && <span className="arp-timer">{clock(total)}</span>}
  </header>
  <div className="arp-body-wrap" aria-hidden={collapsed}><div className="arp-body" inert={collapsed}>
   <div className="arp-meta"><span className="arp-meta-left">{meta}</span><span className="arp-counter">{live ? `Step ${Math.min(steps.length, doneCount + 1)} of ${steps.length}` : `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`}</span></div>
   {segments.length > 0 && <div className="arp-segments" style={{gridTemplateColumns: `repeat(${segments.length}, 1fr)`}}>
    {segments.map((s, i) => <span key={i} className={`arp-seg${s.failed ? ' is-failed' : ''}`}><i style={{width: `${Math.round(s.fill * 100)}%`}}/>{s.running && <b/>}</span>)}
   </div>}
   {steps.length > 0 && <div ref={listRef} className="arp-steps" style={{maxHeight: MAX_ROWS * 26}} onScroll={e => { const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 8; }}>
    {steps.map(step => {
     const start = ms(step.startedAt), end = ms(step.finishedAt);
     const seconds = Number.isFinite(start) ? ((Number.isFinite(end) ? end : isLive(step) ? now : NaN) - start) / 1000 : NaN;
     const args = Object.entries(step.args ?? {}).filter(([, v]) => v !== undefined && v !== '').slice(0, 8);
     return <HoverCard.Root key={step.id} openDelay={160} closeDelay={80} open={openRow === step.id} onOpenChange={o => setOpenRow(r => (o ? step.id : r === step.id ? null : r))}>
      <HoverCard.Trigger asChild>
       <div className={`arp-row is-${step.status}`} tabIndex={0} onClick={() => setOpenRow(r => (r === step.id ? null : step.id))}>
        <span className="arp-row-icon">{iconFor(step.name)}</span>
        <span className="arp-row-label">{step.status === 'awaiting_approval' ? `Awaiting approval: ${stepText(step)}` : stepText(step)}{step.summary && !isLive(step) && <span className="arp-row-summary"> · {step.summary}</span>}</span>
        {step.status === 'error' || step.status === 'denied' ? <X className="arp-row-mark" size={12}/> : null}
        <span className="arp-row-time">{span(seconds)}</span>
       </div>
      </HoverCard.Trigger>
      <HoverCard.Portal><HoverCard.Content className="arp-detail" side={narrow ? 'bottom' : 'right'} align="start" sideOffset={narrow ? 6 : 10} collisionPadding={12}>
       <div className="arp-detail-head"><span className="arp-detail-icon">{iconFor(step.name)}</span><b>{step.label}</b><code>{step.name}</code></div>
       <dl>
        {step.target && <><dt>Target</dt><dd>{step.target}</dd></>}
        <dt>Status</dt><dd className={`is-${step.status}`}>{STATUS_TEXT[step.status]}</dd>
        {Number.isFinite(start) && <><dt>Time</dt><dd>{new Date(start).toLocaleTimeString('en-GB', {hour12: false})}{Number.isFinite(seconds) ? ` · took ${span(seconds)}` : ''}</dd></>}
        {step.summary && <><dt>{step.status === 'error' ? 'Error' : 'Result'}</dt><dd>{step.summary}</dd></>}
       </dl>
       {args.length > 0 && <div className="arp-detail-args"><div className="arp-detail-label">Arguments</div>{args.map(([k, v]) => <div key={k} className="arp-arg"><span>{k}</span><code>{argValue(v)}</code></div>)}</div>}
       {step.savedNote && onOpenNote && <button type="button" className="arp-detail-link" onClick={() => { setOpenRow(null); onOpenNote(step.savedNote!.id, step.savedNote!.title); }}>Open “{step.savedNote.title || step.savedNote.id.split('/').pop()}”</button>}
      </HoverCard.Content></HoverCard.Portal>
     </HoverCard.Root>;
    })}
   </div>}
   {approval && <ApprovalBox approval={approval}/>}
   {extra}
   {(live && onStop || footer) && <div className="arp-foot">
    {live && onStop && <button type="button" className="arp-btn" onClick={e => { e.stopPropagation(); onStop(); }}><Square size={10} strokeWidth={2.2}/>Stop</button>}
    <span className="arp-foot-right">{footer}</span>
   </div>}
  </div></div>
 </section>;
}
