// Shapes of the demo server's JSON (Base/p2e/web/demo_server.py).
import type {RunStep} from './agent-run/agent-run';

export type Workflow = {id: string; letter: string; name: string; desc: string};
export type ModelOption = {id: string; model: string; provider: string; vendor: string; available: boolean};
export type Example = {capsule: string; title: string; language: string; task_prompt: string; questions: string[]};
export type Budget = {month: string; spent_usd: number; limit_usd: number | null; exhausted: boolean};
export type Options = {workflows: Workflow[]; models: ModelOption[]; examples: Example[]; budget?: Budget};

export type Question = {id: string; text: string; answer_type: string; locator: string};
export type Spec = {
  id: string; title: string; objective: string; task_prompt: string; language: string;
  code: {capsule: string | null; repo_url: string | null};
  questions: Question[];
  origin: {source: string; prompt: string};
};

export type NodeKind = 'agent' | 'pipeline' | 'planner' | 'env' | 'executor' | 'answer' | 'worker' | 'run' | 'debug';
export type NodeStatus = 'pending' | 'running' | 'waiting' | 'done' | 'failed' | 'stopped';
export type GraphNode = {
  id: string; parent: string | null; kind: NodeKind; role: string; model: string; task: string;
  status: NodeStatus; cost: number; started: string | null; ended: string | null; summary: string;
  attempt?: number; steps: RunStep[];
};
export type Answer = {
  id: string; question: string; answer: unknown; evidence: string[]; note: string;
  provenance: {status: string; produced_in: string[]} | null;
  correct?: boolean | null;  // CORE-Bench runs only: graded against the ground truth
  reference?: Reference | null;  // what to compare with: the paper's value (demo runs) or CORE-Bench's reference answer
  comparison?: Comparison;
};
export type Reference = {source: 'paper' | 'corebench'; value: unknown; unit?: string; location?: string; quote?: string; arxiv?: string | null};
export type Comparison = {status: 'match' | 'close' | 'scale' | 'mismatch' | 'unknown'; diff?: number; rel?: number | null};
export type PaperValues = {arxiv: string | null; source?: 'paper' | 'corebench'; values: Record<string, Reference>; error?: string};
export type RunWorkspace = {run: string; title: string; size_mb: number; live: boolean; cleans_in_s: number | null};
// fixed: a shared server, where each person's runs go to a folder named after them and are cleaned up after a while
export type Workdir = {path: string; name: string; default: string; chosen: boolean; fixed?: boolean;
  cleanup_min?: number | null; runs?: RunWorkspace[]};
export type HistoryRun = {
  key: string; title: string; workflow: string; profile: string | null; started: number | null;
  status: 'running' | 'done' | 'failed' | 'stopped'; answered: number | null; questions: number;
  wall_s: number | null; cost: number | null;
};
export type ExampleTask = {
  case: string; title: string; source: 'corebench' | 'user'; code: string; language: string; questions: number;
  fastest_s: number; workflows: string[]; run: string;
  demo_s?: number[];  // the run times measured on the demo server, when the examples are a curated list
};
export type AuthState = {required: boolean; ok: boolean; name: string | null; expired: boolean; expires: string | null};
export type Presence = {online: number; names: string[]; me: string | null; running: number; queued: number; max_running: number | null};
export type JobState = {
  phase: 'queued' | 'preparing' | 'running' | 'done' | 'failed' | 'stopped';
  position?: number; running?: number; max_running?: number | null;  // queued: place in line and the slots ahead
  workflow: string; run?: string; spec?: Spec | null; model?: string; profile?: string; vendor?: string; started?: string;  // spec: null until the run wrote spec.json
  nodes: GraphNode[]; answers: Answer[] | null; cost?: number; now: number; error: string | null;
  summary?: {verdict: string; answered?: number; questions?: number; wall_s: number} | null;
};
