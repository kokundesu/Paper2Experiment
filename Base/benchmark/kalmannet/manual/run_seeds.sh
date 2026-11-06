#!/usr/bin/env bash
# Usage (from benchmark/kalmannet/):  manual/run_seeds.sh <claim> <seed> [<seed> ...]
#   claim = lin_T20     : Table I setting, main_linear_canonical.py (2x2, H=I, nu=0 dB, 1/r2=20 dB, T=20)
#           nlobs_30dB  : Table VI setting, main_lor_DT_NLobs.py (repo default: T=20, nu=0 dB, 1/r2=30 dB)
#           nlobs_10dB  : Table VI setting, main_lor_DT_NLobs.py with 1/r2=10 dB
# Logs go to results/logs/<claim>_s<seed>.log. Runs are sequential; small nets are
# Python-overhead bound, so more threads do not help (1, 2 and 4 threads time the same).
set -euo pipefail
cd "$(dirname "$0")/KalmanNet_TSP"
PY=../../../../envs/kalmannet/bin/python
LOGDIR=../../results/logs
mkdir -p "$LOGDIR" KNet
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2} MKL_NUM_THREADS=${MKL_NUM_THREADS:-2}
claim=$1; shift
for seed in "$@"; do
  log="$LOGDIR/${claim}_s${seed}.log"
  start=$(date +%s)
  case $claim in
    lin_T20)    env SEED=$seed RUN_TAG=${claim}_s${seed}_ T=20 INV_R2_DB=20 NU_DB=0 $PY main_linear_canonical.py > "$log" 2>&1 ;;
    nlobs_30dB) env SEED=$seed RUN_TAG=${claim}_s${seed}_ INV_R2_DB=30 $PY main_lor_DT_NLobs.py > "$log" 2>&1 ;;
    nlobs_10dB) env SEED=$seed RUN_TAG=${claim}_s${seed}_ INV_R2_DB=10 $PY main_lor_DT_NLobs.py > "$log" 2>&1 ;;
    *) echo "unknown claim $claim"; exit 1 ;;
  esac
  end=$(date +%s)
  echo "WALL_SECONDS: $((end-start))" >> "$log"
  echo "$claim seed $seed done in $((end-start)) s: $(grep -E 'Kalman Filter - MSE LOSS|MSE Test' "$log" | tr '\n' ' ')"
done
