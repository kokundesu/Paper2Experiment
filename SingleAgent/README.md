# A: SingleAgent (`single`)

One ReAct agent with every tool (read/write files, shell) reads the paper, clones and sets up the repository, runs the
experiments, and submits the measured values (one per seed run, each citing its log) together with a diagnosis.

- **Harness:** `p2e.llm.Agent` executes the tool calls in the sandbox and records every message, tool call and command
  log; the submission is validated (one value per seed) and sent back on error.
- **Verification:** none during the run. The evaluator checks at the end that each value appears in a cited, untampered
  log that shows the run (evidence pattern) and lies within the pre-registered tolerance.
- **Role in the comparison:** the baseline harness (the PaperBench-style ReAct agent).

Tests: [tests/test_single.py](tests/test_single.py).
