---
name: cpu-runtime
description: Use before the first full run on this machine (Apple Silicon, CPU only),
  and whenever a run is far slower than its own estimate.
version: 1
evidence:
- 20261017-143741_v4-itransformer_planner_workers_haiku55
---

When: before full runs, or when a run takes much longer than a short timed run predicted.

Steps
1. Time a short run first (few iterations/epochs) and extrapolate; write the estimate down.
2. Data loading: on macOS, PyTorch DataLoader worker processes (num_workers > 0) are slow to start and often
   slower than none on CPU. Set num_workers to 0 (flag, config or a one-line patch, recorded) unless a timed
   comparison shows workers help.
3. Device: code that asks for CUDA must fall back to CPU (`--device cpu`, `--gpu -1`, or a minimal patch of the
   device selection); never leave it retrying or silently failing.
4. Threads: leave BLAS/OpenMP threads at their default unless runs are started in parallel; then set
   OMP_NUM_THREADS so the runs do not oversubscribe the cores.
5. Avoid repeated work: build caches or preprocessed data once and reuse them across seeds; do not rerun an
   identical command.
6. If a run is over twice its estimate, stop and find why (a hang, a worker pool, a GPU fallback loop, a much
   larger setting than intended) before starting more runs.

Checks
- A full run's time is close to the extrapolated estimate.
