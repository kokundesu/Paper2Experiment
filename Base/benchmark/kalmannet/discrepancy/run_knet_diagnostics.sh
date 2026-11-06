#!/usr/bin/env bash
# KalmanNet training diagnostics (about 70 s per run on an M4 CPU). Run from benchmark/kalmannet/.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); PY=$ROOT/../../envs/kalmannet/bin/python; LOG=$ROOT/results/logs
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4} MKL_NUM_THREADS=${OMP_NUM_THREADS:-4}
run() {  # name db seed COMPOSITION_LOSS
  local f=$LOG/discrepancy_$1.log
  echo "RUN name=$1 code=main inv_r2_db=$2 seed=$3 opts=[KalmanNet training, COMPOSITION_LOSS=$4]" >> "$f"
  local t0=$(date +%s)
  (cd "$ROOT/manual/KalmanNet_TSP" && env SEED=$3 RUN_TAG=disc_$1_db$2_s$3_ INV_R2_DB=$2 COMPOSITION_LOSS=$4 $PY ../../discrepancy/knet_train_main.py) >> "$f" 2>&1
  echo "WALL_SECONDS: $(( $(date +%s) - t0 ))" >> "$f"
  echo "$1 db=$2 seed=$3: $(grep -E 'MSE LOSS|MSE Test' "$f" | tail -2 | tr '\n' ' ')"
}
: > $LOG/discrepancy_knet_state_mse_loss.log; : > $LOG/discrepancy_knet_repo_default_low_snr.log
for s in 0 1 2; do run knet_state_mse_loss 30 $s 0; done          # paper loss (no composition term), 30 dB
run knet_repo_default_low_snr -10 0 1                              # repo defaults at the low-SNR end of Table VI
run knet_repo_default_low_snr 0 0 1
