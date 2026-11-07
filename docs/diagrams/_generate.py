"""Generate the three Paper2Exp diagrams with the diagram-design skin (demo-web tokens)."""
import math
import sys
import unicodedata
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

T = dict(paper="#f9f9f9", paper2="#f1f1f1", ink="#171717", muted="#4a4a4a", soft="#6b6b6b",
         accent="#1664c0", accent_tint="rgba(22,100,192,0.08)", link="#1c7935")
SANS = "'Geist', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
SERIF = "'Instrument Serif', 'Noto Serif SC', 'Songti SC', serif"
MONO = "'Geist Mono', ui-monospace, monospace"
FONTS = ("https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600"
         "&family=Geist+Mono:wght@400;500;600&family=Noto+Sans+SC:wght@400;500;600&family=Noto+Serif+SC:wght@400"
         "&display=swap")


def wide(ch):
    return unicodedata.east_asian_width(ch) in ("W", "F") or 0x2460 <= ord(ch) <= 0x24FF or ch in "→"


def tw(text, size, mono=False):
    adv = 0.62 if mono else 0.60
    return sum(size if wide(c) else size * adv for c in text if unicodedata.category(c) not in ("Mn", "Me"))


def up4(v):
    return int(math.ceil(v / 4.0) * 4)


def has_han(text):
    return any(wide(c) for c in text)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


KIND = {
    "backend": ("#ffffff", T["ink"], ""),
    "focal": (T["accent_tint"], T["accent"], ""),
    "store": ("rgba(23,23,23,0.05)", T["muted"], ""),
    "input": ("rgba(74,74,74,0.10)", T["soft"], ""),
}


def node(x, y, w, h, name, sub=None, line3=None, kind="backend"):
    fill, stroke, _ = KIND[kind]
    cx = x + w / 2
    sw = 1.2 if kind == "focal" else 1
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{T["paper"]}"/>',
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>']
    lines = [l for l in (name, sub, line3) if l]
    # vertical rhythm: name 12px, mono sub 9px, han line 12px
    heights = {"name": 15, "sub": 14, "line3": 16}
    seq = [("name", name)] + ([("sub", sub)] if sub else []) + ([("line3", line3)] if line3 else [])
    total = sum(heights[k] for k, _ in seq)
    base = y + (h - total) / 2
    for k, text in seq:
        base += heights[k]
        if k == "name":
            color = T["accent"] if kind == "focal" else T["ink"]
            out.append(f'<text x="{cx}" y="{base - 3}" class="node-name" fill="{color}">{esc(text)}</text>')
        elif k == "sub":
            out.append(f'<text x="{cx}" y="{base - 4}" class="sublabel">{esc(text)}</text>')
        else:
            out.append(f'<text x="{cx}" y="{base - 3}" class="han-sub">{esc(text)}</text>')
    return "\n".join(out)


def label(cx, cy, text):
    """Arrow label centred at (cx, cy) with an opaque mask. Han -> 12px sans 500, Latin -> 8px mono caps."""
    if has_han(text):
        w, h = up4(tw(text, 12) + 8), 16
        return (f'<rect x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" rx="2" fill="{T["paper"]}"/>'
                f'<text x="{cx}" y="{cy + 4}" class="arrow-label-han">{esc(text)}</text>'), (cx - w / 2, cy - h / 2, w, h)
    w, h = up4(tw(text, 8, True) * 1.06 + 8), 12
    return (f'<rect x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" rx="2" fill="{T["paper"]}"/>'
            f'<text x="{cx}" y="{cy + 3}" class="arrow-label">{esc(text.upper())}</text>'), (cx - w / 2, cy - h / 2, w, h)


def label_above(cx, line_y, text):
    h = 16 if has_han(text) else 12
    return label(cx, line_y - 6 - h / 2, text)[0]


def label_below(cx, line_y, text):
    h = 16 if has_han(text) else 12
    return label(cx, line_y + 6 + h / 2, text)[0]


def label_right(line_x, cy, text):
    w = up4(tw(text, 12) + 8) if has_han(text) else up4(tw(text, 8, True) * 1.06 + 8)
    return label(line_x + 8 + w / 2, cy, text)[0]


def zone(x, y, w, h, text, bottom=False):
    lw = up4(tw(text, 12) + 16)
    if bottom:
        y_lab = y + h
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="rgba(23,23,23,0.02)" '
                f'stroke="rgba(23,23,23,0.14)" stroke-width="0.8"/>'
                f'<rect x="{x + 16}" y="{y_lab - 8}" width="{lw}" height="16" rx="2" fill="{T["paper"]}"/>'
                f'<text x="{x + 16 + lw / 2}" y="{y_lab + 4}" class="zone-label">{esc(text)}</text>')
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="rgba(23,23,23,0.02)" '
            f'stroke="rgba(23,23,23,0.14)" stroke-width="0.8"/>'
            f'<rect x="{x + 16}" y="{y - 8}" width="{lw}" height="16" rx="2" fill="{T["paper"]}"/>'
            f'<text x="{x + 16 + lw / 2}" y="{y + 4}" class="zone-label">{esc(text)}</text>')


def path(d, kind="muted", dashed=False):
    stroke = {"muted": T["muted"], "accent": T["accent"], "soft": T["soft"], "link": T["link"]}[kind]
    marker = {"muted": "arrow", "accent": "arrow-accent", "soft": "arrow-soft", "link": "arrow-link"}[kind]
    dash = ' stroke-dasharray="5,4"' if dashed else ""
    sw = 1 if dashed else 1.2
    return f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}"{dash} marker-end="url(#{marker})"/>'


def legend(y, width, items):
    out = [f'<line x1="40" y1="{y - 16}" x2="{width - 40}" y2="{y - 16}" stroke="rgba(23,23,23,0.10)" stroke-width="0.8"/>',
           f'<text x="40" y="{y + 4}" class="legend-eyebrow">LEGEND</text>']
    x = 120
    for kind, text in items:
        if kind in KIND:
            fill, stroke, _ = KIND[kind]
            out.append(f'<rect x="{x}" y="{y - 8}" width="24" height="16" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        else:
            k, dashed = (kind.split(":") + [""])[:2]
            out.append(path(f"M{x},{y} H{x + 24}", k, dashed == "dashed"))
        out.append(f'<text x="{x + 32}" y="{y + 4}" class="legend-text">{esc(text)}</text>')
        x += 32 + up4(tw(text, 12)) + 36
    return "\n".join(out)


def page(slug, eyebrow, title, desc, vw, vh, body, extra_css=""):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <link href="{FONTS}" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --paper: {T['paper']}; --ink: {T['ink']}; --muted: {T['muted']}; --soft: {T['soft']};
      --accent: {T['accent']}; --accent-tint: {T['accent_tint']}; --link: {T['link']};
      --sans: {SANS}; --serif: {SERIF}; --mono: {MONO};
    }}
    body {{ min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 3rem 2rem;
           background: var(--paper); color: var(--ink); font-family: var(--sans); }}
    .frame {{ width: 100%; max-width: {vw + 40}px; }}
    .eyebrow {{ margin-bottom: 0.5rem; color: var(--muted); font: 500 0.66rem var(--mono); letter-spacing: 0.18em; text-transform: uppercase; }}
    h1 {{ margin-bottom: 1.5rem; color: var(--ink); font: 400 clamp(1.5rem, 2.4vw + 0.75rem, 2rem)/1.15 var(--serif); letter-spacing: -0.02em; }}
    .diagram-container {{ width: 100%; overflow-x: auto; }}
    svg {{ display: block; width: 100%; min-width: {vw}px; }}
    @media print {{ .diagram-container {{ overflow-x: visible; }} svg {{ min-width: 0; }} }}
    .node-name {{ font: 600 12px var(--sans); text-anchor: middle; }}
    .sublabel {{ fill: var(--soft); font: 400 9px var(--mono); text-anchor: middle; }}
    .han-sub {{ fill: var(--soft); font: 400 12px var(--sans); text-anchor: middle; }}
    .arrow-label {{ fill: var(--soft); font: 400 8px var(--mono); letter-spacing: 0.06em; text-anchor: middle; }}
    .arrow-label-han {{ fill: var(--soft); font: 500 12px var(--sans); text-anchor: middle; }}
    .zone-label {{ fill: var(--soft); font: 500 12px var(--sans); text-anchor: middle; }}
    .legend-eyebrow {{ fill: var(--muted); font: 500 8px var(--mono); letter-spacing: 0.14em; }}
    .legend-text {{ fill: var(--muted); font: 400 12px var(--sans); }}
    .callout {{ fill: var(--muted); font: italic 400 14px var(--serif); }}
    {extra_css}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">{esc(eyebrow)}</p>
    <h1>{esc(title)}</h1>
    <div class="diagram-container">
      <svg viewBox="0 0 {vw} {vh}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{slug}-title {slug}-desc">
        <title id="{slug}-title">{esc(title)}</title>
        <desc id="{slug}-desc">{esc(desc)}</desc>
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{T['muted']}"/></marker>
          <marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{T['accent']}"/></marker>
          <marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{T['link']}"/></marker>
          <marker id="arrow-soft" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{T['soft']}"/></marker>
        </defs>
        <rect width="{vw}" height="{vh}" fill="{T['paper']}"/>
{body}
      </svg>
    </div>
  </div>
</body>
</html>
"""


# ------------------------------------------------------------------ 1. architecture
def architecture():
    b = []
    # zones first
    b.append(zone(272, 112, 480, 288, "工作流（每次运行选一个）"))
    b.append(zone(272, 448, 480, 120, "共享基础设施", bottom=True))
    # arrows
    b.append(path("M224,234 H248 Q256,234 256,226 V176 Q256,168 264,168 H296"))
    b.append(path("M224,256 H296"))
    b.append(path("M224,278 H248 Q256,278 256,286 V336 Q256,344 264,344 H296"))
    for x, t in ((360, "调用模型"), (512, "执行命令"), (664, "读取技能")):
        b.append(path(f"M{x},400 V472"))
        b.append(label_right(x, 420, t))
    b.append(path("M752,256 H880", "accent"))
    b.append(label_above(816, 256, "答案 + 引用日志"))
    b.append(path("M976,152 V216"))
    b.append(label_right(976, 184, "目标值 + 容差"))
    b.append(path("M512,544 V592 Q512,600 520,600 H968 Q976,600 976,592 V296"))
    b.append(label_right(976, 448, "日志 + sha256"))
    # nodes
    b.append(node(48, 212, 176, 88, "复现任务", "task.yaml / spec.yaml", "论文或 CORE-Bench 胶囊", "input"))
    b.append(node(296, 136, 432, 64, "A · 单个 ReAct Agent", "single · SingleAgent/"))
    b.append(node(296, 224, 432, 64, "B · 固定六角色流水线", "fixed · Multiagent/FixedPipeline/"))
    b.append(node(296, 312, 432, 64, "D · Planner + 验证型 Runtime", "planner_workers · Multiagent/PlannerWorkers/"))
    b.append(node(296, 472, 128, 72, "LLM 层", "llm.py · models.yaml"))
    b.append(node(448, 472, 128, 72, "沙箱", "sandbox.py", "每条命令一份日志"))
    b.append(node(600, 472, 128, 72, "技能库", "skills/*/SKILL.md"))
    b.append(node(880, 88, 192, 64, "隐藏真值", "case.yaml", kind="store"))
    b.append(node(880, 216, 192, 80, "评估器（无 LLM）", "evaluator.py", "→ full / partial / fail", "focal"))
    b.append('<text x="1096" y="112" class="callout">agent 永远读不到它：</text>')
    b.append('<text x="1096" y="132" class="callout">沙箱命令守卫会拦截</text>')
    b.append(legend(672, 1280, [("input", "输入"), ("backend", "组件"), ("store", "隐藏数据"),
                                ("focal", "焦点"), ("accent", "主结果流"), ("muted", "调用 / 数据")]))
    return page("p2e-architecture", "Architecture · Paper2Exp", "Paper2Exp 整体架构",
                "复现任务交给三种工作流之一；三者共用 LLM 层、沙箱和技能库；评估器不用 LLM，"
                "只拿隐藏真值、agent 的答案和沙箱写下的带 sha256 的日志来判定。",
                1280, 720, "\n".join(b))


# ------------------------------------------------------------------ 2. D runtime
def planner_runtime():
    b = []
    b.append(zone(40, 96, 296, 480, "LLM：只提议，不执行"))
    b.append(zone(400, 96, 840, 480, "确定性 Runtime（p2e/runtime.py）"))
    # arrows
    b.append(path("M188,152 V132 Q188,124 196,124 H1100 Q1108,124 1108,132 V152"))
    b.append(label_below(964, 124, "提议结束"))
    b.append(path("M304,176 H432"))
    b.append(label_above(368, 176, "提交补丁"))
    b.append(path("M432,200 H304", "soft", dashed=True))
    b.append(label_below(368, 200, "拒绝 + 原因"))
    b.append(path("M632,176 H720"))
    b.append(label_above(676, 176, "原子应用"))
    b.append(path("M820,224 V296"))
    b.append(label_right(820, 260, "run 任务"))
    b.append(path("M920,332 H1008"))
    b.append(label_above(964, 332, "通过"))
    b.append(path("M820,368 V440"))
    b.append(label_right(820, 404, "失败"))
    b.append(path("M1108,368 V468 Q1108,476 1100,476 H920"))
    b.append(label_right(1108, 416, "数值或失败"))
    b.append(path("M720,200 H688 Q680,200 680,208 V456 Q680,464 672,464 H304"))
    b.append(label_above(520, 464, "agent 任务"))
    b.append(path("M304,488 H720"))
    b.append(label_below(520, 488, "结构化报告"))
    b.append(path("M820,512 V544 Q820,552 812,552 H56 Q48,552 48,544 V196 Q48,188 56,188 H72", "accent"))
    b.append(label_above(560, 552, "只给变化 + 进度"))
    # nodes
    b.append(node(72, 152, 232, 72, "Planner", "ExperimentPatch", "唯一的规划者", "input"))
    b.append(node(72, 440, 232, 72, "Worker 子 agent", "setup / debug / diagnose", "每个任务一个新上下文", "input"))
    b.append(node(432, 152, 200, 72, "① 补丁校验", "plan check", "不许过滤输出 · 要冒烟命令"))
    b.append(node(720, 152, 200, 72, "执行就绪任务", "task DAG", "依赖都完成才运行"))
    b.append(node(1008, 152, 200, 72, "结束关卡", "finish gate", "值够数或答案有出处", "focal"))
    b.append(node(720, 296, 200, 72, "② 冒烟运行", "smoke_command", "缩短版命令须跑通"))
    b.append(node(1008, 296, 200, 72, "③ 完整运行 + 证据", "exit 0 · metric · log", "日志里要有数值和进度"))
    b.append(node(720, 440, 200, 72, "唤醒 Planner", "delta · stall counter", "停滞 3 次 → 重新规划"))
    b.append(legend(616, 1280, [("input", "LLM 角色"), ("backend", "确定性步骤"), ("focal", "唯一出口"),
                                ("muted", "流程"), ("accent", "回到 Planner"), ("soft:dashed", "打回")]))
    return page("p2e-planner-runtime", "Architecture · Version D", "D 版本：Planner 提议，Runtime 把关",
                "Planner 提交任务补丁，确定性 Runtime 依次做补丁校验、冒烟运行、完整运行与证据检查，"
                "agent 任务交给隔离的 Worker；Runtime 只把变化唤醒给 Planner，且只有结束关卡能结束一次运行。",
                1280, 660, "\n".join(b))


# ------------------------------------------------------------------ 3. skills loop
def skills_loop():
    cx, cy, R = 400, 356, 260
    sw, sh, hw, hh = 160, 64, 200, 104
    stations = [
        ("开发集运行", "A · B · D on dev split", "记录用量"),
        ("摘要", "digest · no answers", None),
        ("策展", "curate · LLM proposes", None),
        ("泄漏检查", "check · no ids / values", None),
        ("发布新版", "apply · history/vN", "新版本"),
    ]
    focal = 3
    N = len(stations)
    centers = []
    for k in range(N):
        th = math.radians(-90 + k * 360 / N)
        centers.append((cx + R * math.cos(th), cy + R * math.sin(th)))
    rects = []
    for (px, py) in centers:
        x = round((px - sw / 2) / 4) * 4
        y = round((py - sh / 2) / 4) * 4
        rects.append((x, y))
    # recompute centres from rounded rects so arcs meet edges exactly
    rc = [(x + sw / 2, y + sh / 2) for x, y in rects]

    def ang(p):
        return math.atan2(p[1] - cy, p[0] - cx) % (2 * math.pi)

    def hits(k):
        x, y = rects[k]
        pts = []
        for xe in (x, x + sw):
            d = R * R - (xe - cx) ** 2
            if d >= 0:
                for s in (1, -1):
                    yy = cy + s * math.sqrt(d)
                    if y <= yy <= y + sh:
                        pts.append((xe, yy))
        for ye in (y, y + sh):
            d = R * R - (ye - cy) ** 2
            if d >= 0:
                for s in (1, -1):
                    xx = cx + s * math.sqrt(d)
                    if x <= xx <= x + sw:
                        pts.append((xx, ye))
        return pts

    def entry_exit(k):
        th = ang(rc[k])
        pts = hits(k)
        def rel(p):
            return (ang(p) - th + math.pi) % (2 * math.pi) - math.pi
        before = min((p for p in pts if rel(p) < 0), key=lambda p: abs(rel(p)))
        after = min((p for p in pts if rel(p) > 0), key=lambda p: abs(rel(p)))
        return before, after

    b = []
    for k in range(N):
        j = (k + 1) % N
        _, ex = entry_exit(k)
        en, _ = entry_exit(j)
        phi = math.atan2(en[1] - cy, en[0] - cx) - 1.2 / R
        q = (cx + R * math.cos(phi), cy + R * math.sin(phi))
        b.append(f'<path class="ring" d="M{ex[0]:.3f} {ex[1]:.3f} A{R} {R} 0 0 1 {q[0]:.3f} {q[1]:.3f}" marker-end="url(#arrow)"/>')

    def box_d(u, a, bb):
        terms = []
        if abs(u[0]) > 1e-9:
            terms.append(a / abs(u[0]))
        if abs(u[1]) > 1e-9:
            terms.append(bb / abs(u[1]))
        return min(terms)

    for k, (_, _, sl) in enumerate(stations):
        if not sl:
            continue
        px, py = rc[k]
        dx, dy = cx - px, cy - py
        L = math.hypot(dx, dy)
        u = (-dx / L, -dy / L)  # from hub outward
        ds = box_d(u, sw / 2, sh / 2)
        dh = box_d(u, hw / 2, hh / 2)
        s = (px - ds * u[0], py - ds * u[1])
        e = (cx + (dh + 6) * u[0], cy + (dh + 6) * u[1])
        if abs(s[0] - e[0]) < 0.01:
            b.append(f'<path class="spoke" d="M{s[0]:.0f} {s[1]:.0f} V{e[1]:.0f}" marker-end="url(#arrow-soft)"/>')
        else:
            b.append(f'<path class="spoke" d="M{s[0]:.3f} {s[1]:.3f} L{e[0]:.3f} {e[1]:.3f}" marker-end="url(#arrow-soft)"/>')
        mx, my = (s[0] + e[0]) / 2, (s[1] + e[1]) / 2
        w = up4(tw(sl, 12) + 8)
        if abs(s[0] - e[0]) < 0.01:
            b.append(label(mx + 8 + w / 2, my, sl)[0])
        else:
            # offset perpendicular to the spoke, on the side away from the ring flow
            nx, ny = u[1], -u[0]
            off = 8 + w / 2 + 2
            b.append(label(mx + nx * off, my + ny * off, sl)[0])

    for k, (name, sub, _) in enumerate(stations):
        x, y = rects[k]
        b.append(node(x, y, sw, sh, name, sub, kind="focal" if k == focal else "backend"))
    hx, hy = cx - hw / 2, cy - hh / 2
    b.append(f'<rect x="{hx}" y="{hy}" width="{hw}" height="{hh}" rx="8" fill="{T["ink"]}"/>')
    b.append(f'<text x="{cx}" y="{cy - 4}" class="hub-name">技能库</text>')
    b.append(f'<text x="{cx}" y="{cy + 18}" class="hub-sub">skills/ · read_skill · vN</text>')
    b.append('<text x="744" y="508" class="callout">跑测试集之前先 freeze：</text>')
    b.append('<text x="744" y="530" class="callout">测试集的运行不进入这个循环</text>')
    b.append(legend(672, 960, [("muted", "每轮的步骤"), ("soft:dashed", "写回技能库"), ("focal", "防泄漏关卡")]))
    css = (".ring { fill: none; stroke: var(--muted); stroke-width: 1.2; }"
           " .spoke { fill: none; stroke: var(--soft); stroke-width: 1; stroke-dasharray: 5 4; }"
           " .hub-name { fill: var(--paper); font: 600 16px var(--sans); text-anchor: middle; }"
           " .hub-sub { fill: var(--paper); opacity: 0.78; font: 400 9px var(--mono); text-anchor: middle; }")
    return page("p2e-skills-loop", "Loop · Skill library", "技能库的逐轮升级循环",
                "每轮开发集运行后，摘要、LLM 策展、泄漏检查、发布新版依次进行，新版本写回技能库供下一轮使用；"
                "测试集运行前冻结技能库。", 960, 720, "\n".join(b), css)


# ------------------------------------------------------------------ 4. workflow comparison
def workflows():
    b = []
    b.append(zone(40, 96, 368, 504, "A · 单个 ReAct Agent（single）"))
    b.append(zone(456, 96, 368, 504, "B · 固定六角色流水线（fixed）"))
    b.append(zone(872, 96, 368, 504, "D · Planner + Runtime（planner_workers）"))

    # A: one agent loops over the sandbox; nothing checks it until the evaluator
    b.append(path("M184,208 V296"))
    b.append(label_right(184, 252, "工具调用"))
    b.append(path("M264,296 V208", "soft", dashed=True))
    b.append(label_right(264, 252, "输出"))
    b.append(path("M224,360 V640", "accent"))
    b.append(label_right(224, 512, "答案 + 引用日志"))
    b.append('<text x="88" y="440" class="callout">运行中途</text>')
    b.append('<text x="88" y="462" class="callout">没有任何检查</text>')
    b.append(node(88, 128, 272, 80, "ReAct Agent", "all tools · one context", "读论文 → 装环境 → 跑实验 → 提交", "input"))
    b.append(node(88, 296, 272, 64, "沙箱", "read / write / shell", "每条命令一份日志"))

    # B: code routes six LLM roles and a deterministic executor
    roles = [("Paper Analyst", "读论文，列出要复现的结果", "input"),
             ("Env Agent", "克隆仓库、装环境", "input"),
             ("Planner", "写实验命令", "input"),
             ("Executor ⇄ Debugger", "确定性执行 · 最多 4 次调试", "backend"),
             ("Result Reviewer", "试跑后审一次结果", "input"),
             ("Discrepancy Analyst", "诊断与论文不符的原因", "input")]
    ys = [128 + i * 70 for i in range(len(roles))]
    for y in ys[:-1]:
        b.append(path(f"M640,{y + 48} V{y + 70}"))
    b.append(path(f"M640,{ys[-1] + 48} V640", "accent"))
    b.append(label_right(640, 604, "答案 + 引用日志"))
    for y, (name, sub, kind) in zip(ys, roles):
        b.append(node(504, y, 272, 48, name, None, sub, kind))

    # D: the Planner proposes, the runtime verifies and is the only exit
    b.append(path("M1000,208 V272"))
    b.append(label_right(1000, 240, "提交补丁"))
    b.append(path("M1112,272 V208", "soft", dashed=True))
    b.append(label_right(1112, 240, "变化 + 进度"))
    b.append(path("M984,352 V440"))
    b.append(label_right(984, 396, "派发"))
    b.append(path("M1072,440 V352", "soft", dashed=True))
    b.append(label_right(1072, 396, "报告"))
    b.append(path("M1192,352 V640", "accent"))
    txt = "只有 Runtime 能结束"
    b.append(label(1192 - 8 - up4(tw(txt, 12) + 8) / 2, 560, txt)[0])
    b.append(node(904, 128, 304, 80, "Planner", "ExperimentPatch", "唯一的规划者，只提议不执行", "input"))
    b.append(node(904, 272, 304, 80, "确定性 Runtime", "runtime.py · task DAG",
                  "① 补丁校验 ② 冒烟运行 ③ 证据检查", "focal"))
    for i, w in enumerate(("setup", "debug", "diagnose")):
        b.append(node(904 + i * 84, 440, 76, 56, w, "worker", kind="input"))
    b.append('<text x="904" y="530" class="callout">每个 worker 一个新上下文</text>')

    # shared evaluator
    b.append(node(40, 640, 1200, 64, "评估器（无 LLM）", "evaluator.py · 三个版本用同一套评分",
                  "答案须在容差内，且出现在沙箱写下的未被改动的日志里 → full / partial / fail", "focal"))
    b.append(legend(760, 1280, [("input", "LLM 角色"), ("backend", "确定性组件"), ("focal", "验证 / 出口"),
                                ("muted", "流程"), ("accent", "提交结果"), ("soft:dashed", "返回")]))
    return page("p2e-workflows", "Comparison · Workflows", "三种工作流对比",
                "A：一个 ReAct agent 持有全部工具，只在最后由评估器检查；B：代码把任务依次路由给六个 LLM 角色和确定性执行器；"
                "D：一个 Planner 提交补丁，确定性 Runtime 做三道检查、把 agent 任务交给隔离的 worker，并且只有它能结束运行。"
                "三者最后都交给同一个不用 LLM 的评估器。", 1280, 800, "\n".join(b))


for name, fn in (("01-architecture.html", architecture), ("02-planner-runtime.html", planner_runtime),
                 ("03-skills-loop.html", skills_loop), ("04-workflows.html", workflows)):
    (OUT / name).write_text(fn(), encoding="utf-8")
    print("wrote", OUT / name)
