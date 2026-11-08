// The way into a shared demo server: a name and the 4-digit access code, on a card over a frosted copy of the home
// page. The digit boxes and their motion are adapted from Le Thanh's OTP Input on 21st.dev
// (@minhxthanh/components/otp-input): four boxes that rise in, lift on focus, shake on a wrong code and slide together
// into a tick on the right one. The server keeps the session in a cookie until the code expires, so a returning
// visitor goes straight in under the same name. Without an access code (one's own machine) the page opens at once.
import {useCallback, useEffect, useRef, useState, type ReactNode} from 'react';
import {AnimatePresence, motion, useAnimationControls} from 'motion/react';
import {Languages} from 'lucide-react';
import {api, LOCKED_EVENT} from './api';
import {useLang} from './i18n';
import type {AuthState} from './types';

const DIGITS = 4;
const NAME_KEY = 'p2e-name';
type State = 'idle' | 'error' | 'success';

const remembered = () => { try { return localStorage.getItem(NAME_KEY) ?? ''; } catch { return ''; } };

function Mark({size = 26}: {size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <path d="M8.5 2.5C8.7 6.1 9.9 7.3 13.5 7.5C9.9 7.7 8.7 8.9 8.5 12.5C8.3 8.9 7.1 7.7 3.5 7.5C7.1 7.3 8.3 6.1 8.5 2.5Z" fill="#2E7CF6"/>
    <path d="M14.5 11.8C14.6 13.2 15.1 13.7 16.5 13.8C15.1 13.9 14.6 14.4 14.5 15.8C14.4 14.4 13.9 13.9 12.5 13.8C13.9 13.7 14.4 13.2 14.5 11.8Z" fill="#76A9FA"/>
  </svg>;
}

/** The home page as it looks before a request, drawn without any data: what the frosted glass sits on. */
function Backdrop() {
  const {L} = useLang();
  return <div className="gate-backdrop" aria-hidden="true">
    <div className="app">
      <header className="topbar app-topbar">
        <div className="topbar-left"><Mark size={20}/><span className="agents-title">Paper2Exp</span>
          <span className="topbar-sub">{L('reproduction demo', '论文复现演示')}</span></div>
      </header>
      <main className="layout is-empty"><section className="chat">
        <div className="hero">
          <h1>{L('What should we reproduce?', '想复现什么？')}</h1>
          <p>{L('Name the paper or code and the numbers or figures you want, ideally with the GitHub address. I’ll turn it into a task, run it with the workflow and model below, and compare the results with the paper.',
            '说出论文或代码，以及想复现的数字或图，最好附上 GitHub 地址。我会把它整理成任务，用下面选的 workflow 和模型运行，再把结果和论文对比。')}</p>
          <div className="suggest"><span className="suggest-btn">{L('KalmanNet, Table I (signal processing, 8–16 min)', 'KalmanNet 表 I（信号处理，8–16 分钟）')}</span>
            <span className="suggest-btn">{L('A request without the code’s address', '一个没给代码地址的请求')}</span></div>
        </div>
        <div className="composer"><div className="composer-field"><div className="gate-fake-input">{L('Start by typing…', '输入你的请求…')}</div></div>
          <div className="composer-tray"><span/><span/></div></div>
      </section></main>
    </div>
  </div>;
}

function CheckIcon({size = 16}: {size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>;
}

function DigitBox({index, state, inputRef, onDigit, onBack, onMove, onPasteDigits}: {
  index: number; state: State; inputRef: (el: HTMLInputElement | null) => void;
  onDigit: (i: number, d: string) => void; onBack: (i: number) => void; onMove: (i: number) => void; onPasteDigits: (i: number, ds: string[]) => void;
}) {
  const controls = useAnimationControls();
  const spring = {type: 'spring' as const, stiffness: 700, damping: 20};
  useEffect(() => {
    controls.start({opacity: 1, y: 0, transition: {...spring, delay: index * 0.05}});
    return () => controls.stop();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // on the right code the boxes slide into the first one
    if (state === 'success') controls.start({x: -index * 68, transition: {type: 'spring', stiffness: 300, damping: 30, delay: index * 0.06}});
  }, [state, index, controls]);
  const ring = state === 'error' ? 'gate-digit is-error' : state === 'success' ? 'gate-digit is-ok' : 'gate-digit';
  return <motion.div className={ring} initial={{opacity: 0, y: 10}} animate={controls}>
    <input ref={inputRef} type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={DIGITS} aria-label={`digit ${index + 1}`}
      disabled={state === 'success'}
      onFocus={() => controls.start({y: -5, transition: spring})} onBlur={() => controls.start({y: 0, transition: spring})}
      onInput={e => {  // one digit typed, or several at once (autofill, a fast keyboard): spread them over the boxes
        const ds = e.currentTarget.value.replace(/\D/g, '').split('');
        if (ds.length === 1) onDigit(index, ds[0]); else if (ds.length > 1) onPasteDigits(index, ds); else e.currentTarget.value = '';
      }}
      onKeyDown={e => {
        if (e.key === 'Backspace' && !e.currentTarget.value) onBack(index);
        else if (e.key === 'ArrowLeft') onMove(index - 1);
        else if (e.key === 'ArrowRight') onMove(index + 1);
      }}
      onPaste={e => { e.preventDefault(); onPasteDigits(index, e.clipboardData.getData('text').replace(/\D/g, '').split('')); }}/>
  </motion.div>;
}

function CodeCard({auth, onEnter}: {auth: AuthState; onEnter: () => void}) {
  const {lang, setLang, L} = useLang();
  const [name, setName] = useState(remembered);
  const [state, setState] = useState<State>(auth.expired ? 'error' : 'idle');
  const [message, setMessage] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [welcome, setWelcome] = useState('');
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const nameRef = useRef<HTMLInputElement>(null);
  const shake = useAnimationControls();
  const expires = auth.expires ? new Date(auth.expires) : null;
  const expiresText = expires ? expires.toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-GB', {year: 'numeric', month: 'long', day: 'numeric'}) : '';

  useEffect(() => { (name ? inputs.current[0] : nameRef.current)?.focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const code = () => inputs.current.map(i => i?.value ?? '').join('');
  const clear = () => { inputs.current.forEach(i => { if (i) i.value = ''; }); inputs.current[0]?.focus(); };
  const fail = useCallback((text: string, reset = true) => {
    setState('error'); setMessage(text);
    shake.start({x: [0, 5, -5, 5, -5, 0], transition: {duration: 0.3}});
    // empty the boxes for the next try (not waiting on the animation: its promise is not reliable across re-renders)
    if (reset) setTimeout(() => { clear(); setState('idle'); }, 900);
  }, [shake]);

  const submit = useCallback(async () => {
    const c = code();
    if (c.length < DIGITS || busy) return;
    const who = name.trim();
    if (!who) { setMessage(L('Enter your name first, so the others can see who is online.', '请先填写你的名字，组员可以看到谁在线。')); setState('error'); nameRef.current?.focus(); return; }
    setBusy(true);
    const r = await api.tryCode(c, who).catch(() => ({ok: false} as {ok: boolean; reason?: string}));
    setBusy(false);
    if (r.ok) {
      try { localStorage.setItem(NAME_KEY, who); } catch { /* private mode */ }
      setMessage(''); setWelcome(who); setState('success');
      setTimeout(onEnter, 1800);
      return;
    }
    const res = r as {reason?: string; tries_left?: number; retry_after?: number};
    if (res.reason === 'expired') fail(L(`This access code expired${expiresText ? ` on ${expiresText}` : ''}. Ask the project owner for a new one.`, `访问码${expiresText ? `已于${expiresText}` : '已经'}过期，请向项目负责人索取新的访问码。`), false);
    else if (res.reason === 'too_many') fail(L(`Too many wrong tries. Try again in ${Math.ceil((res.retry_after ?? 60) / 60)} min.`, `尝试次数过多，请 ${Math.ceil((res.retry_after ?? 60) / 60)} 分钟后再试。`));
    else if (res.reason === 'wrong') fail(res.tries_left
      ? L(`That code is not right. ${res.tries_left} ${res.tries_left === 1 ? 'try' : 'tries'} left.`, `访问码不正确，还可以再试 ${res.tries_left} 次。`)
      : L('That code is not right.', '访问码不正确。'));
    else fail(L('Could not reach the server. Try again.', '无法连接服务器，请重试。'));
  }, [busy, name, L, fail, expiresText, onEnter]);

  const onDigit = (i: number, d: string) => {
    const el = inputs.current[i]; if (el) el.value = d;
    if (i < DIGITS - 1) inputs.current[i + 1]?.focus();
    if (code().length === DIGITS) submit(); else if (state === 'error' && !auth.expired) { setState('idle'); setMessage(''); }
  };
  const onBack = (i: number) => { if (i > 0) { const el = inputs.current[i - 1]; if (el) { el.value = ''; el.focus(); } } };
  const onMove = (i: number) => inputs.current[Math.max(0, Math.min(DIGITS - 1, i))]?.focus();
  const onPasteDigits = (i: number, ds: string[]) => {
    ds.slice(0, DIGITS - i).forEach((d, k) => { const el = inputs.current[i + k]; if (el) el.value = d; });
    onMove(Math.min(i + ds.length, DIGITS - 1));
    setTimeout(submit, 0);
  };

  return <div className="gate-card">
    <button type="button" className="gate-lang" onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')} aria-label={L('Language', '语言')}>
      <Languages size={13}/>{lang === 'zh' ? 'English' : '中文'}</button>
    <div className="gate-logo"><Mark/></div>
    <h1 className="gate-title">{state === 'success' ? L(`Welcome, ${welcome}`, `欢迎，${welcome}`) : L('Enter the Paper2Experiment demo', '进入 Paper2Experiment 演示')}</h1>
    <AnimatePresence mode="wait">
      {state === 'success'
        ? <motion.div key="ok" className="gate-ok" initial={{opacity: 0, y: 20}} animate={{opacity: 1, y: 0}} exit={{opacity: 0}} transition={{duration: 0.3}}>
          <motion.div className="gate-ok-badge" initial={{opacity: 0, scale: 0.5}} animate={{opacity: 1, scale: 1}}
            transition={{delay: 0.25, opacity: {duration: 0.2}, scale: {type: 'spring', stiffness: 500, damping: 30}}}><CheckIcon size={30}/></motion.div>
          <motion.p initial={{opacity: 0, x: -10}} animate={{opacity: 1, x: 0}} transition={{delay: 0.4, duration: 0.4}}>
            {L('You’re in. Opening the demo…', '验证通过，正在打开演示…')}</motion.p>
        </motion.div>
        : <motion.div key="form" initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} transition={{duration: 0.2}}>
          <p className="gate-desc">{L('Pick the name the others will see you by, then type the 4-digit access code you were given.',
            '填写一个组员能认出你的名字，再输入项目负责人分享的 4 位访问码。')}</p>
          <label className="gate-name">
            <span>{L('Your name', '你的名字')}</span>
            <input ref={nameRef} value={name} maxLength={24} placeholder={L('e.g. Allen', '例如：小明')}
              onChange={e => { setName(e.target.value); if (state === 'error' && !auth.expired) { setState('idle'); setMessage(''); } }}
              onKeyDown={e => { if (e.key === 'Enter') { if (code().length === DIGITS) submit(); else inputs.current[code().length]?.focus(); } }}/>
          </label>
          <div className="gate-code-label">{L('Access code', '访问码')}</div>
          <div className="gate-digits-wrap">
            <motion.div className="gate-digits" animate={shake}>
              {Array.from({length: DIGITS}, (_, i) => <DigitBox key={i} index={i} state={state} inputRef={el => { inputs.current[i] = el; }}
                onDigit={onDigit} onBack={onBack} onMove={onMove} onPasteDigits={onPasteDigits}/>)}
            </motion.div>
            <AnimatePresence>{message && <motion.div className="gate-error" initial={{opacity: 0, y: 10}} animate={{opacity: 1, y: 0}}
              exit={{opacity: 0, y: -10}} transition={{duration: 0.2}}>{message}</motion.div>}</AnimatePresence>
          </div>
          <p className="gate-foot">{expiresText ? L(`The code works until ${expiresText}. You stay signed in on this device until then.`,
            `访问码有效期至${expiresText}，在此之前本设备会保持登录。`) : L('You stay signed in on this device.', '本设备会保持登录。')}</p>
        </motion.div>}
    </AnimatePresence>
  </div>;
}

/** Shows the page once the visitor may use it: at once without an access code, else after the code card. */
export function Gate({children}: {children: ReactNode}) {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [open, setOpen] = useState(false);
  const check = useCallback(() => api.auth().then(a => { setAuth(a); setOpen(!a.required || a.ok); },
    () => setOpen(true)), []);  // no answer at all: let the page show its own "cannot reach the server"
  useEffect(() => { check(); }, [check]);
  useEffect(() => {  // the session ended while the page was open (the code expired): back to the card
    const lock = () => { setOpen(false); check(); };
    window.addEventListener(LOCKED_EVENT, lock);
    return () => window.removeEventListener(LOCKED_EVENT, lock);
  }, [check]);
  useEffect(() => {  // the gate is drawn before the app sets the theme
    try { document.documentElement.classList.toggle('dark', localStorage.getItem('p2e-theme') === 'dark'); } catch { /* private mode */ }
  }, []);
  if (open) return <>{children}</>;
  return <div className="gate">
    <Backdrop/>
    <div className="gate-glass"/>
    {auth && <div className="gate-center"><CodeCard auth={auth} onEnter={() => setOpen(true)}/></div>}
  </div>;
}
