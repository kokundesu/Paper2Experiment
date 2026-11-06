#!/usr/bin/env bash
# Usage: run_seeds.sh <tag> <N_U> <N_F> <LAYERS> <NEURONS> <seed> [<seed> ...]
# Runs the patched Burgers.py once per seed, appends one row per run to
# results/burgers_<tag>.csv and writes logs to results/logs/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CASE="$(dirname "$HERE")"
PY="${PY:-$CASE/../../envs/pinn/bin/python}"   # override for diagnostics
tag=$1 nu=$2 nf=$3 nl=$4 nn=$5; shift 5
mkdir -p "$CASE/results/logs"
cd "$HERE/PINNs/appendix/continuous_time_inference (Burgers)"   # script uses relative ../Data paths
for s in "$@"; do
  SEED=$s N_U=$nu N_F=$nf LAYERS=$nl NEURONS=$nn RESULTS_CSV="$CASE/results/burgers_$tag.csv" \
    "$PY" Burgers.py > "$CASE/results/logs/${tag}_seed$s.log" 2>&1
  grep -E 'Error u|Optimizer' "$CASE/results/logs/${tag}_seed$s.log" | sed "s/^/[$tag seed $s] /"
done
