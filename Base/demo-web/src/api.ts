import type {AuthState, ExampleTask, HistoryRun, JobState, Options, PaperValues, Presence, Spec, Workdir} from './types';

/** Fired when the server says the session is gone (the access code expired): the gate takes the page back. */
export const LOCKED_EVENT = 'p2e-locked';

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({error: `HTTP ${res.status}`}));
  if (res.status === 401 && data.error === 'locked') window.dispatchEvent(new Event(LOCKED_EVENT));
  if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}

/** The code check answers with a status and a reason, not an error to throw. */
async function tryCode(code: string, name: string): Promise<{ok: boolean; reason?: 'wrong' | 'too_many' | 'expired' | 'name'; tries_left?: number; retry_after?: number}> {
  const res = await fetch('/api/auth', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code, name})});
  return res.json().catch(() => ({ok: false}));
}

export const api = {
  auth: () => call<AuthState>('/api/auth'),
  tryCode,
  /** this page is open (id: one per browser); people online, runs running and waiting */
  presence: (id: string) => call<Presence>('/api/presence', {id}),
  /** forget this browser's session (to sign in under another name) */
  logout: () => fetch('/api/logout', {method: 'POST'}),
  options: () => call<Options>('/api/options'),
  examples: () => call<{examples: ExampleTask[]}>('/api/examples'),
  // me: the signed-in name on a shared server (runs are then one's own unless `all`), null on one's own machine
  history: (all = false) => call<{runs: HistoryRun[]; me: string | null}>(all ? '/api/history?all=1' : '/api/history'),
  workdir: (runs = false) => call<Workdir>(runs ? '/api/workdir?runs=1' : '/api/workdir'),
  setWorkdir: (path: string) => call<Workdir>('/api/workdir', {path}),
  /** the macOS folder dialog on the machine the server runs on; `cancelled` when dismissed */
  chooseWorkdir: () => call<Workdir & {cancelled?: boolean}>('/api/workdir/choose', {}),
  /** an example task as a fresh spec, with the values its answers will be compared with */
  example: (kase: string) => call<{spec: Spec; paper: PaperValues}>('/api/example', {case: kase}),
  /** the spec drafted from the request, or {need: 'repo_url'} when there is no code to run */
  draft: (body: {prompt: string; capsule?: string; repo_url?: string; model: string}) =>
    call<{spec: Spec; paper: PaperValues; cost: number} | {need: 'repo_url'}>('/api/draft', body),
  start: (body: {spec: Spec; workflow: string; model: string}) => call<{key: string}>('/api/start', body),
  job: (key: string) => call<JobState>(`/api/jobs/${encodeURIComponent(key)}`),
  stop: (key: string) => call<{stopped: boolean}>(`/api/jobs/${encodeURIComponent(key)}/stop`, {}),
  fileUrl: (key: string, path: string) => `/api/jobs/${encodeURIComponent(key)}/file?path=${encodeURIComponent(path)}`,
};
