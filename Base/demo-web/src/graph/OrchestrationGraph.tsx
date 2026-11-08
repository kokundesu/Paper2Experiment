// The multi-agent graph of agents_multi_agent_orchestration_graph.html, fed by a live run instead of the canned video:
// same cards (avatar, role, model, status badge, task with tool badges, cost · time, collapse button) and the same
// connectors. The original placed eight fixed cards; here the tree comes from the run: the root on top, its children
// in a row (four per row, then the next row), and under each card a branch with its latest steps (tool calls, the one
// running now lit up) followed by its own children, indented 48px like the original's sub-agents. The root's steps
// hang to its right when its children take the space below it.
import {useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {X} from 'lucide-react';
import type {RunStep} from '../agent-run/agent-run';
import {Avatar, ROLE_ICONS, toolIcon} from '../icons';
import type {GraphNode, NodeStatus} from '../types';
import './graph.css';
import {useLang} from '../i18n';

const W = 324, H = 168, COL = 385, ROW_GAP = 61, INDENT = 48, MAX_COLS = 4, R = 10;
const SW = W - INDENT, SH = 50, SP = 60, GAP = 18, STEPS_SHOWN = 3;
const PAD = 8;  // room around the drawing for the current card's ring
const MIN_SCALE = 0.6;  // below this the cards' text is too small to read: the window scrolls instead

const BADGE: Record<NodeStatus, {cls: string; label: [string, string]; icon: ReactNode}> = {
  running: {cls: 'running', label: ['Running', '运行中'], icon: <svg className="spinner-svg" width="12" height="12" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="5.2" stroke="var(--badge-running-track)" strokeWidth="1.8"/>
    <path d="M7 1.8A5.2 5.2 0 0 1 12.2 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>},
  done: {cls: 'done', label: ['Done', '完成'], icon: <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
    <path d="M2.8 7.3L5.6 10.1L11.2 4.2" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"/></svg>},
  waiting: {cls: 'needs-you', label: ['Waiting', '等待中'], icon: <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="5.3" stroke="currentColor" strokeWidth="1.5"/>
    <path d="M7 4.2V7.2L8.8 8.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>},
  failed: {cls: 'failed', label: ['Failed', '失败'], icon: <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
    <path d="M6.02 2.3L1.5 10.2C1.1 10.9 1.6 11.8 2.42 11.8H11.58C12.4 11.8 12.9 10.9 12.5 10.2L7.98 2.3C7.57 1.6 6.43 1.6 6.02 2.3Z" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M7 5.5V7.8" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round"/><circle cx="7" cy="9.7" r="0.65" fill="currentColor"/></svg>},
  stopped: {cls: 'stopped', label: ['Stopped', '已停止'], icon: <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
    <rect x="2.2" y="2.2" width="7.6" height="7.6" rx="1.8" stroke="currentColor" strokeWidth="1.45"/></svg>},
  pending: {cls: 'stopped', label: ['Queued', '排队中'], icon: <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
    <circle cx="6" cy="6" r="4.4" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2 2"/></svg>},
};

function duration(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
}

export function seconds(n: GraphNode, now: number) {
  if (!n.started) return 0;
  const end = n.ended ? Date.parse(n.ended) : now;
  return (end - Date.parse(n.started)) / 1000;
}

function stepSeconds(s: RunStep, now: number) {
  if (!s.startedAt) return NaN;
  const end = s.finishedAt ? Date.parse(s.finishedAt) : s.status === 'running' ? now : NaN;
  return (end - Date.parse(s.startedAt)) / 1000;
}

type Pos = {x: number; y: number};
type StepItem = {key: string; owner: string; step?: RunStep; more?: number; x: number; y: number};
type Path = {d: string; cls?: string};

/** The steps a card shows in its branch: the latest few, after a "N earlier" item when there are more. */
function branchSteps(n: GraphNode): {step?: RunStep; more?: number}[] {
  if (n.kind === 'pipeline' || (n.kind === 'run' && n.steps.length <= 1)) return [];
  const shown = n.steps.slice(-STEPS_SHOWN).map(step => ({step}));
  return n.steps.length > STEPS_SHOWN ? [{more: n.steps.length - STEPS_SHOWN}, ...shown] : shown;
}

/** Card and step positions plus the connector paths; the canvas size follows from them. */
function layout(nodes: GraphNode[], collapsed: Set<string>) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const kids = new Map<string, GraphNode[]>();
  for (const n of nodes) if (n.parent && byId.has(n.parent)) kids.set(n.parent, [...(kids.get(n.parent) ?? []), n]);
  const root = nodes.find(n => !n.parent || !byId.has(n.parent));
  const pos = new Map<string, Pos>();
  const steps: StepItem[] = [];
  const paths: Path[] = [];
  const circles: Pos[] = [];
  if (!root) return {pos, steps, paths, circles, width: W, height: H, kids};

  const stepItem = (n: GraphNode, s: {step?: RunStep; more?: number}, x: number, y: number) => {
    steps.push({key: s.step ? s.step.id : `${n.id}-more`, owner: n.id, step: s.step, more: s.more, x, y});
    return s.step?.status === 'running' ? ' step-branch is-live' : ' step-branch';
  };
  /** A card, then its branch: steps, then its children (each with its own branch). Returns the bottom edge. */
  const column = (n: GraphNode, x: number, y: number): number => {
    pos.set(n.id, {x, y});
    const branches: {y: number; x: number; cls: string}[] = [];
    let cursor = y + H + GAP, bottom = y + H;  // bottom: the lowest edge drawn in this column
    if (!collapsed.has(n.id)) {
      for (const s of branchSteps(n)) {
        branches.push({y: cursor + SH / 2, x: x + INDENT, cls: stepItem(n, s, x + INDENT, cursor)});
        bottom = cursor + SH;
        cursor += SP;
      }
      for (const c of kids.get(n.id) ?? []) {
        branches.push({y: cursor + 42, x: x + INDENT, cls: c.status === 'stopped' ? ' stopped-branch' : ''});
        bottom = column(c, x + INDENT, cursor);
        cursor = bottom + GAP;
      }
    }
    const hasBranch = (kids.get(n.id) ?? []).length > 0 || branchSteps(n).length > 0;
    if (hasBranch) {
      const rx = x + 24, cy = y + H + 1;
      circles.push({x: rx, y: cy});
      if (!branches.length) paths.push({d: `M ${rx} ${cy + 4} L ${rx} ${cy + 14}`});
      else {
        paths.push({d: `M ${rx} ${cy + 4} L ${rx} ${branches[branches.length - 1].y - R}`});
        for (const b of branches) paths.push({d: `M ${rx} ${b.y - R} Q ${rx} ${b.y} ${rx + R} ${b.y} L ${b.x} ${b.y}`, cls: b.cls});
      }
    }
    return bottom;
  };

  const row1 = collapsed.has(root.id) ? [] : kids.get(root.id) ?? [];
  if (!row1.length) {  // a single agent, or a Planner before its first task: its steps hang below it
    const bottom = column(root, 0, 0);
    const xs = [...pos.values()].map(p => p.x + W).concat(steps.map(s => s.x + SW));
    return {pos, steps, paths, circles, width: Math.max(W, ...xs), height: bottom, kids};
  }
  const cols = Math.min(MAX_COLS, row1.length);
  let width = Math.max(W, cols * COL - ROW_GAP);
  const rootX = row1.length === 1 ? 0 : (width - W) / 2;
  pos.set(root.id, {x: rootX, y: 0});

  // the root's own steps: to its right, on a branch out of its side
  let rootBottom = H;
  const rootSteps = branchSteps(root);
  if (rootSteps.length) {
    const spine = rootX + W + 28, sx = spine + 28;
    const ys = rootSteps.map((s, i) => { const y = 42 - SH / 2 + i * SP; return {y: y + SH / 2, cls: stepItem(root, s, sx, y)}; });
    paths.push({d: `M ${rootX + W} 42 L ${spine} 42 L ${spine} ${ys[ys.length - 1].y - (ys.length > 1 ? R : 0)}`});
    for (const b of ys.slice(1)) paths.push({d: `M ${spine} ${b.y - R} Q ${spine} ${b.y} ${spine + R} ${b.y} L ${sx} ${b.y}`, cls: b.cls});
    paths.push({d: `M ${spine} 42 L ${sx} 42`, cls: ys[0].cls});
    width = Math.max(width, sx + SW);
    rootBottom = Math.max(rootBottom, ys[ys.length - 1].y + SH / 2);
  }

  let top = rootBottom + ROW_GAP;
  const rows: {top: number; ids: string[]}[] = [];
  for (let i = 0; i < row1.length; i += cols) {
    const ids = row1.slice(i, i + cols).map(n => n.id);
    let bottom = top + H;
    ids.forEach((id, c) => { bottom = Math.max(bottom, column(byId.get(id)!, row1.length === 1 ? rootX : c * COL, top)); });
    rows.push({top, ids});
    top = bottom + ROW_GAP;
  }

  // root -> first-row cards: a trunk down from the root's circle, a bus above each row, a drop to each card
  const ox = rootX + W / 2, cy = H + 1;
  circles.push({x: ox, y: cy});
  rows.forEach(({top: rowTop, ids}, r) => {
    const busY = rowTop - 31;
    paths.push({d: `M ${ox} ${(r === 0 ? cy : rows[r - 1].top + 2) + 4} L ${ox} ${busY}`});
    for (const id of ids) {
      const cx = pos.get(id)!.x + W / 2;
      const cls = byId.get(id)?.status === 'stopped' ? ' stopped-branch' : '';
      if (Math.abs(cx - ox) < 1) paths.push({d: `M ${ox} ${busY} L ${ox} ${rowTop}`, cls});
      else {
        const dir = cx > ox ? 1 : -1;
        paths.push({d: `M ${ox} ${busY} L ${cx - dir * R} ${busY} Q ${cx} ${busY} ${cx} ${busY + R} L ${cx} ${rowTop}`, cls});
      }
    }
  });
  const xs = [...pos.values()].map(p => p.x + W).concat(steps.map(s => s.x + SW));
  return {pos, steps, paths, circles, width: Math.max(width, ...xs), height: top - ROW_GAP, kids};
}

function Card({node, provider, pos, now, current, selected, branchCount, collapsed, onToggle, onSelect}: {
  node: GraphNode; provider: string; pos: Pos; now: number; current: boolean; selected: boolean; branchCount: string;
  collapsed: boolean; onToggle: () => void; onSelect: () => void;
}) {
  const {L} = useLang();
  const badge = BADGE[node.status] ?? BADGE.running;
  const RoleIcon = ROLE_ICONS[node.kind];
  const tools = [...new Set(node.steps.map(s => s.name))].filter(n => n !== 'submit').slice(-3);
  const isTask = node.kind === 'worker' || node.kind === 'run';
  const model = isTask ? `${node.kind === 'worker' ? 'Worker' : 'Runtime'}${node.kind === 'worker' && node.model ? ` · ${node.model}` : ''}${node.attempt && node.attempt > 1 ? ` · ${L(`attempt ${node.attempt}`, `第 ${node.attempt} 次尝试`)}` : ''}` : node.model;
  return <article className={`agent-card${node.status === 'stopped' ? ' status-stopped' : ''}${current ? ' is-current' : ''}${selected ? ' is-selected' : ''}`}
    style={{left: pos.x, top: pos.y}} onClick={onSelect} role="button" tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter') onSelect(); }}>
    <div className="card-top">
      <div className="agent-identity">
        <div className="model-avatar"><Avatar provider={provider} kind={node.kind}/></div>
        <div className="agent-titles">
          <div className="agent-role"><RoleIcon className="role-icon" size={14} strokeWidth={2}/>{node.role}</div>
          <div className="agent-model">{model}</div>
        </div>
      </div>
      <div className={`status-badge ${badge.cls}`}>{badge.icon}<span>{L(...badge.label)}</span></div>
    </div>
    <p className="card-task">
      {tools.length > 0 && <span className="tool-stack">{tools.map(t => <span key={t} className="tool-badge" title={t}>{toolIcon(t)}</span>)}</span>}
      {node.summary && node.status === 'failed' ? node.summary : node.task || '…'}
    </p>
    <div className="card-bottom">
      <div className="card-metrics">
        <span className="metric-cost">{node.kind === 'run' || node.kind === 'executor' ? L(`${node.steps.length} ${node.steps.length === 1 ? 'command' : 'commands'}`, `${node.steps.length} 条命令`) : `$${node.cost.toFixed(node.cost < 0.1 ? 3 : 2)}`}</span>
        <span className="metric-dot">·</span>
        <span className="metric-time">{duration(seconds(node, now))}</span>
      </div>
      {branchCount && <button type="button" className={`collapse-btn${collapsed ? ' is-collapsed' : ''}`}
        onClick={e => { e.stopPropagation(); onToggle(); }}>
        <span>{collapsed ? `+${branchCount}` : branchCount}</span>
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
          <path d={collapsed ? 'M4.5 2.5L8 6L4.5 9.5' : 'M2.5 4.5L6 8L9.5 4.5'} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>}
    </div>
  </article>;
}

/** One step in a card's branch; the running one is lit and says so. */
function StepCard({item, now, onSelect}: {item: StepItem; now: number; onSelect: () => void}) {
  const {L} = useLang();
  const s = item.step;
  if (!s) return <div className="step-card is-more" style={{left: item.x, top: item.y, width: SW, height: SH}} onClick={onSelect}>
    <span className="step-text">{L(`${item.more} earlier ${item.more === 1 ? 'step' : 'steps'} · click the card for all`, `之前还有 ${item.more} 步 · 点击卡片查看全部`)}</span>
  </div>;
  const secs = stepSeconds(s, now);
  return <div className={`step-card is-${s.status}`} style={{left: item.x, top: item.y, width: SW, height: SH}} onClick={onSelect}
    title={`${s.label}${s.target ? `: ${s.target}` : ''}${s.summary ? `\n${s.summary}` : ''}`}>
    <span className="step-icon">{toolIcon(s.name)}</span>
    <span className="step-body">
      <span className="step-label">{s.status === 'running' && <i className="step-now">NOW</i>}{s.label}</span>
      <span className="step-target">{s.target || s.summary || ''}</span>
    </span>
    <span className="step-meta">
      {s.status === 'running' ? <svg className="spinner-svg" width="12" height="12" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="5.2" stroke="var(--badge-running-track)" strokeWidth="1.8"/>
        <path d="M7 1.8A5.2 5.2 0 0 1 12.2 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
        : s.status === 'error' || s.status === 'denied' ? <X size={12}/> : null}
      {Number.isFinite(secs) && <span>{duration(secs)}</span>}
    </span>
  </div>;
}

export function OrchestrationGraph({nodes, provider, now, currentId, selectedId, onSelect}: {
  nodes: GraphNode[]; provider: string; now: number; currentId: string | null; selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const g = useMemo(() => layout(nodes, collapsed), [nodes, collapsed]);
  // fit the whole graph into the window it sits in (.graph-scroll): never above 1, never below MIN_SCALE
  const outer = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState({w: 1140, h: 560});
  useLayoutEffect(() => {
    const box = outer.current?.closest('.graph-scroll') as HTMLElement | null;
    if (!box) return;
    const ro = new ResizeObserver(() => setAvail({w: box.clientWidth, h: box.clientHeight}));
    ro.observe(box);
    return () => ro.disconnect();
  }, []);
  const scale = Math.max(MIN_SCALE, Math.min(1, avail.w / (g.width + 2 * PAD), (avail.h - 24) / (g.height + 2 * PAD)));
  // keep the card in view that is working right now
  useEffect(() => {
    const p = currentId ? g.pos.get(currentId) : undefined;
    const el = outer.current?.closest('.graph-scroll') as HTMLElement | null;
    if (!p || !el) return;
    const y = p.y * scale;
    if (y < el.scrollTop + 20 || y + (H + 3 * SP) * scale > el.scrollTop + el.clientHeight)
      el.scrollTo({top: Math.max(0, y - 60), behavior: 'smooth'});
  }, [currentId]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={outer} className="graph-outer" style={{height: (g.height + 2 * PAD) * scale + 4, width: Math.max(avail.w, (g.width + 2 * PAD) * scale)}}>
    <main className="graph-canvas" style={{width: g.width + 2 * PAD, height: g.height + 2 * PAD, transform: `scale(${scale})`, transformOrigin: 'top left',
      marginLeft: Math.max(0, (avail.w - (g.width + 2 * PAD) * scale) / 2)}}>
      <svg className="connections-svg" viewBox={`${-PAD} ${-PAD} ${g.width + 2 * PAD} ${g.height + 2 * PAD}`}>
        {g.paths.map((p, i) => <path key={i} className={`conn-path${p.cls ?? ''}`} d={p.d}/>)}
        {g.circles.map((c, i) => <circle key={i} className="conn-node-circle" cx={c.x} cy={c.y} r={4}/>)}
      </svg>
      <div style={{position: 'absolute', inset: PAD}}>{/* absolute children sit relative to this inset box, not the padding */}
        {nodes.filter(n => g.pos.has(n.id)).map(n => {
          const children = (g.kids.get(n.id) ?? []).length, nsteps = branchSteps(n).length ? n.steps.length : 0;
          const count = children ? String(children) : nsteps ? `${nsteps} ${nsteps === 1 ? 'step' : 'steps'}` : '';
          return <Card key={n.id} node={n} provider={provider} pos={g.pos.get(n.id)!} now={now} current={n.id === currentId}
            selected={n.id === selectedId} branchCount={count} collapsed={collapsed.has(n.id)} onSelect={() => onSelect(n.id)}
            onToggle={() => setCollapsed(s => { const t = new Set(s); if (t.has(n.id)) t.delete(n.id); else t.add(n.id); return t; })}/>;
        })}
        {g.steps.map(s => <StepCard key={s.key} item={s} now={now} onSelect={() => onSelect(s.owner)}/>)}
      </div>
    </main>
  </div>;
}
