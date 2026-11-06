# B: FixedPipeline (`fixed`)

The v3.1 multi-agent workflow: six LLM roles and a deterministic executor in a LangGraph StateGraph whose routing is
written in code (`_next_step`), not decided by an LLM.

Paper Analyst → Env Agent → Planner → Executor ⇄ Debugger (at most 4 sessions) → Result Reviewer (once, after one
pilot run per claim) → Executor → Discrepancy Analyst (may hand runs back once, for setup errors) → evaluator.

- Numbers come only from the executor's logs. Each role has only the tools it needs and its own budget share.
- Every node is checkpointed (SQLite); `p2e resume` continues an interrupted run.
- **Known weakness (v3.0 held-out runs):** no role has global oversight, so an upstream mistake (e.g. a command that
  prints no training progress) is only caught by the evaluator at the end.

- **Spec runs (CORE-Bench):** Environment Engineer → Planner (commands per question) → Executor ⇄ Debugger →
  Answerer (answers from logs and output files; may hand commands back once for a missing output) → scoring.

Tests: [tests/test_fixed.py](tests/test_fixed.py), [tests/test_fixed_spec.py](tests/test_fixed_spec.py).
