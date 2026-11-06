#!/usr/bin/env bash
# Run one DLinear claim (multivariate, look-back 336) for several seeds with the
# official hyperparameters from scripts/EXP-LongForecasting/Linear/<data>.sh.
# Usage (from benchmark/dlinear/):
#   manual/run_seeds.sh <claim_id> <data> <pred_len> <batch_size> <lr> <seed> [<seed> ...]
# Each run writes results/logs/<claim_id>_s<seed>.log and appends a row to results/dlinear_runs.csv.
set -euo pipefail
CASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$CASE_DIR/../../envs/dlinear/bin/python"
claim=$1 data=$2 pred=$3 bs=$4 lr=$5; shift 5
SEQ_LEN=${SEQ_LEN:-336}  # official value; override only for diagnostics
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TORCH_NUM_THREADS=4
CSV="$CASE_DIR/results/dlinear_runs.csv"
[ -f "$CSV" ] || echo "claim_id,data,pred_len,batch_size,lr,seed,mse,mae,droplast_mse,droplast_mae,test_windows,epochs_run,wall_s" > "$CSV"
cd "$CASE_DIR/manual/LTSF-Linear"
for seed in "$@"; do
  log="$CASE_DIR/results/logs/${claim}_s${seed}.log"
  t0=$(python3 -c 'import time; print(time.time())')
  SEED=$seed "$PY" -u run_longExp.py --is_training 1 --root_path ./dataset/ --data_path "$data.csv" \
    --model_id "${data}_${SEQ_LEN}_${pred}" --model DLinear --data "$data" --features M \
    --seq_len "$SEQ_LEN" --pred_len "$pred" --enc_in 7 --des Exp --itr 1 \
    --batch_size "$bs" --learning_rate "$lr" --num_workers 0 > "$log" 2>&1
  t1=$(python3 -c 'import time; print(time.time())')
  wall=$(python3 -c "print(round($t1-$t0,1))")
  echo "wall_clock_s:$wall" >> "$log"
  python3 - "$log" "$claim" "$data" "$pred" "$bs" "$lr" "$seed" "$wall" >> "$CSV" <<'EOF'
import re, sys
log, *meta = sys.argv[1:]
t = open(log).read()
mse, mae = re.findall(r"^mse:([0-9.eE+-]+), mae:([0-9.eE+-]+)", t, re.M)[-1]
dmse, dmae = re.findall(r"^droplast_mse:([0-9.eE+-]+), droplast_mae:([0-9.eE+-]+)", t, re.M)[-1]
nwin = re.findall(r"^test_windows:(\d+)", t, re.M)[-1]
epochs = len(re.findall(r"^Epoch: \d+, Steps", t, re.M))
claim, data, pred, bs, lr, seed, wall = meta
print(",".join([claim, data, pred, bs, lr, seed, mse, mae, dmse, dmae, nwin, str(epochs), wall]))
EOF
  tail -1 "$CSV"
done
