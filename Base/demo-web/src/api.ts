import type {ExampleTask, HistoryRun, JobState, Options, PaperValues, Spec, Workdir} from './types';

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({error: `HTTP ${res.status}`}));
  if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}

export const api = {
  options: () => call<Options>('/api/options'),
  examples: () => call<{examples: ExampleTask[]}>('/api/examples'),
  history: () => call<{runs: HistoryRun[]}>('/api/history'),
  workdir: () => call<Workdir>('/api/workdir'),
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
