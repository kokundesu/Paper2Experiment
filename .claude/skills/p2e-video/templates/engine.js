// Frame-exact scene engine shared by the group clips: scenes carry data-start (s), elements .in carry data-t
// (s, relative to their scene). A renderer calls seek(t) once per frame; nothing depends on wall-clock time.
(() => {
  const clamp = x => Math.max(0, Math.min(1, x));
  const out3 = x => 1 - Math.pow(1 - clamp(x), 3);
  const smooth = x => { x = clamp(x); return x * x * (3 - 2 * x); };
  const scenes = [...document.querySelectorAll('.scene')].map(el => ({ el, start: parseFloat(el.dataset.start) }));
  window.seek = t => {
    let cur = 0;
    scenes.forEach((s, i) => { if (t >= s.start) cur = i; });
    scenes.forEach((s, i) => {
      const next = scenes[i + 1] ? scenes[i + 1].start : Infinity;
      let op = 0, sc = 1;
      if (i === cur) { op = i === 0 ? 1 : smooth((t - s.start) / .6); sc = i === 0 ? 1 : .98 + .02 * out3((t - s.start) / .9); }
      else if (i === cur - 1) { const k = t - next; op = 1 - smooth(k / .6); sc = 1 + .03 * out3(k / .9); }
      s.el.style.opacity = op; s.el.style.transform = `scale(${sc})`;
      if (op === 0) return;
      const local = i === cur ? t - s.start : next - s.start;
      s.el.querySelectorAll('.in[data-t]').forEach(e => {
        const p = out3((local - parseFloat(e.dataset.t)) / .6);
        e.style.opacity = p; e.style.transform = `translateY(${18 * (1 - p)}px)`;
      });
      s.el.querySelectorAll('[data-type]').forEach(e => {   // typewriter: data-type = start time, 18 chars/s
        const full = e.dataset.text || (e.dataset.text = e.textContent);
        const n = Math.max(0, Math.floor((local - parseFloat(e.dataset.type)) * 18));
        e.textContent = full.slice(0, n);
      });
      s.el.querySelectorAll('[data-hl]').forEach(e => e.classList.toggle('hl', local >= parseFloat(e.dataset.hl)));
    });
    const tag = document.getElementById('tag');
    if (tag) { tag.innerHTML = scenes[cur].el.dataset.tag || ''; tag.style.opacity = scenes[cur].el.dataset.tag ? 1 : 0; }
    const sub = document.getElementById('sub');
    const cue = (window.SUBS || []).find(([a, b]) => t >= a && t < b);
    if (sub) { sub.style.display = cue ? 'block' : 'none'; if (cue) sub.textContent = cue[2]; }
  };
  window.seek(0);
})();
