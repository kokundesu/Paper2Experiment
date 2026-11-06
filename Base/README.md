# Paper2Exp / Base

Shared infrastructure of Paper2Exp: the `p2e` package (sandbox, model layer, agent loop, runtime, executor,
evaluator, CLI, web UI), the benchmark cases and the shared tests. The workflow versions live next to this folder
(`SingleAgent/`, `Multiagent/<Version>/`); see the [repository README](../README.md) for the layout, the versions
and usage. History of the project before v4 (EE6008, single vs fixed pipeline): [docs/OVERVIEW.en.md](docs/OVERVIEW.en.md)
· [docs/OVERVIEW.zh.md](docs/OVERVIEW.zh.md).

## Run directory

```
runs/<stamp>_<case>_<workflow>[_<profile>][_r<n>]/
  trace.jsonl       every event: each model-visible message (rebuildable with p2e.llm.replay_messages), each LLM
                    response, tool call and result, executor/runtime event (task added / failed / done, gates, wakes)
  logs/             full output of every command (smoke_<task>, exp_<task>, shell commands of agents)
  log_manifest.json sha256 of every log the sandbox wrote (saved at the end; used by the evaluator)
  workspace         link to the sandbox (cloned repo, venv, paper) under ~/Library/Caches/p2e/workspaces/<run>/
                    (P2E_WORKSPACE_ROOT), with checkpoints.sqlite for resumable versions; deleted once the run is
                    scored, unless --keep-workspace
  metrics.json, discrepancy_report.json, eval.json, summary.json (+ version-specific json files)
```

## Web UI

`p2e serve` starts a local server (standard library only) and opens the page. Two views:

- **实时工作流 / live workflow.** Every run directory is listed; a run without `summary.json` whose
  `trace.jsonl` is still growing is shown as running. Selecting a run shows its pipeline stages (Paper Analyst →
  Env Agent → Planner → Executor pilot → Result Reviewer → Executor → Discrepancy Analyst → Evaluator for
  multi-agent; derived from the roles' `start` / `end` events and the executor's `run` events), the budget meter,
  the claims with the values measured so far, the event feed (every LLM turn, tool call, executor run and
  submission, trimmed) and each role's JSON output. Running runs are polled every 2 s. The page can also launch
  `p2e run` for a case / workflow / repeat count as a subprocess and stop it.
- **Single vs Multi 对比 / comparison.** All finished runs, re-scored with the current evaluator and case.yaml
  (so the numbers agree with `p2e eval` and the reports), filterable by version and case: full / partial /
  fail counts, mean wall time, cost, requests and tool calls, detection, false success, false alarm and
  attribution per workflow; the full rate per version; verdicts per case; and a dot plot of every measured
  aggregate per claim against the paper value and its tolerance band. Version labels come from
  `runs/all_versions_rescored.json` when present; runs not listed there are `V2.1+`.

The server only reads `runs/` and the benchmark; it never writes into a run directory. It binds to 127.0.0.1.

Settings via environment or `.env` (git-ignored; a variable already exported in the shell wins):

| Variable | Default | Meaning |
|---|---|---|
| `P2E_MODEL` | `gpt-6-luna` | model for every agent (`gpt-6-sol` is the larger, 20x dearer option) |
| `P2E_EFFORT` | `medium` | reasoning effort: `none` / `low` / `medium` / `high` / `xhigh` / `max` |
| `P2E_REVIEW_EFFORT` | `high` | reasoning effort of the multi-agent roles that judge results against the paper (Result Reviewer, Discrepancy Analyst); the single agent always runs at `P2E_EFFORT`, so set this to `medium` for an equal-effort comparison |
| `P2E_RUN_BUDGET_USD` | `5.0` | hard cap on LLM spend per run, shared by all agents (stops one large request early: ~$0.02 on Luna, ~$0.46 on Sol) |
| `P2E_BASE_URL` | `https://api.openai.com/v1` | an inherited `OPENAI_BASE_URL` is deliberately ignored |

Agents use the Responses API, because on GPT-6 Chat Completions allows function calling only with reasoning
effort `none`. Cost is tracked per request from the API's usage (cached input, cache writes and the 2x/1.5x
long-context rate above 272k input tokens included).

In multi-agent runs each role also has its own cap as a share of the run budget: Paper Analyst 15%,
Env Agent 40%, Planner 15%, each Debugger session 25%, Discrepancy Analyst 20% (skipped if the run budget is
already spent; the run is still scored).

## Failure diagnosis

When a number does not match the paper, the agents must say why. (Every agent is told that a run's full output must go to its command log: the log is the only evidence the evaluator accepts.) The single agent and the multi-agent
Discrepancy Analyst write `discrepancy_report.json`: per claim a `status` (reproduced / discrepancy /
not_measured), a root-cause `category` (reproducer_error, paper_code_mismatch, underspecified_paper,
randomness, environment, paper_error, unknown), the competing hypotheses with evidence for and against
(and the log of the diagnostic run that tested each), a conclusion and a confidence. The analyst may run
cheap diagnostic experiments but never retunes hyperparameters, and its runs never change the metrics.

The evaluator grades the report against `discrepancies:` in case.yaml, still without an LLM, and adds it to
`eval.json` / `summary.json` without touching the verdict:

| Metric | Meaning |
|---|---|
| detection | failing claims the agent flagged as discrepancy (or not_measured when there is no value); "failing" means a numerical miss (outside tolerance, too few seeds, no value), not an evidence-only failure |
| false_success | failing claims the agent called reproduced: the honesty metric |
| attribution | ground-truth entries whose category (or an `also_acceptable` one) the agent named; only for claims that failed in this run, `confidence: unresolved` entries excluded |
| strict_attribution | same entries, but a right category counts only if the agent's text also hits at least one `decisive_evidence` item (when the entry lists any) |
| evidence_recall | heuristic: share of `key_evidence` items whose keywords mostly appear in the agent's text |

Strict attribution exists because a category alone can be right for the wrong reason (e.g. DLinear
"paper_code_mismatch" because "seeds are not reported", when the real cause is an older code version). Each
`decisive_evidence` item in case.yaml is `{fact, any_of: [phrases]}`; it is hit when any phrase occurs in that
claim's conclusion or hypotheses (case-insensitive plain substring, whitespace collapsed, no regex). A
discrepancy diagnosis must have a non-empty `conclusion`, so there is text to check.

A run without a report scores detection and attribution 0 ("no diagnosis"). `p2e table` shows them as
`det`, `attr`, `strict` and `false_succ`.

**Pre-registered criterion.** The runner reads each claim's tolerance, the aggregate (mean / median) and the
seed count from case.yaml and states them in the task brief ("Reproduced if: the median over at least 3 seed
runs is within ±1% (relative) of the paper value"); the target value and everything else in case.yaml stay
hidden. Agents judge reproduced / discrepancy by that criterion, the same one the evaluator applies. (A global
"2-3% counts as consistent" rule of thumb used before 2026-10-05 removed false alarms on DLinear but produced
false successes on SGC, whose tolerance is 0.5 pp.)

**Evidence.** Each submitted value must be printed by a cited log that also matches the claim's
`evidence_pattern` (proof the run itself happened; every benchmark claim has one). A summary log may be cited
alongside, but a number an agent printed by hand cannot carry a value. Values are one per seed run, never an
aggregate; the single agent's submission is sent back if a claim has fewer values than seeds.

**Paper text vs official command.** When the authors' own command or script for reproducing a table disagrees
with the paper's text (SGC: README trains Citeseer for 150 epochs, the text says 100), agents use the official
command for the measurement, run the paper-text setting once as a diagnostic and report both.

Claims that the human reproduction showed do not reproduce from the released code are marked
`diagnostic_only: true` in case.yaml (each needs a `discrepancies:` entry). They are measured and reported like
any other claim but left out of the full/partial/fail verdict, so the verdict measures what can be reproduced
and the diagnosis measures whether the agent explains what cannot. task.yaml lists them like every other claim:
agents are not told which ones they are. Current ones: DLinear `etth1_720_mse` (paper numbers come from the
pre-August-2022 code) and KalmanNet `knet_nlobs_30dB` / `ekf_nlobs_30dB` (the paper's EKF row matches a
zero-gain filter); see each case's DISCREPANCY.md.

## Sandbox limits

Workspace isolation (2026-10-06): run workspaces live outside the project tree, and every sandboxed command gets
`UV_NO_PROJECT=1`, `UV_NO_CONFIG=1` and `GIT_CEILING_DIRECTORIES=<run's workspace home>`. Before that, an agent's
`uv run` inside `runs/<run>/workspace/repo` adopted this project's `pyproject.toml`, wrote `uv.lock` into the
project root and re-synced the project's `.venv`, and `git` anywhere under `runs/` resolved to this repository.

The local sandbox isolates by convention: separate workspace, killed process group on timeout, API keys
removed from the environment, and a guard that blocks commands touching `benchmark/`, `case.yaml` or `.env`.
It does not stop a determined process from reading other files on the machine; a Docker backend with the
same `Sandbox.run` interface would close that gap.

Log integrity: the agent's shell can write into `logs/` (a real run did `... | tee ../logs/cmd_010_shell.log`),
so it could forge a log and cite it. The sandbox therefore keeps an in-memory manifest of the sha256 of every
log it writes itself (BLOCKED ones included); only after all agents are done does the runner save it as
`log_manifest.json` and pass it to the evaluator, which then accepts a cited log only if it is `logs/<name>`,
listed in the manifest and unchanged ("log not written by the sandbox" / "log modified after it was written"
otherwise). `p2e eval` uses the saved manifest when present; manual calibration and older runs skip the check.
