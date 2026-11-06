#!/usr/bin/env bash
# Discrepancy experiments for DLinear ETTh1 (multivariate, look-back 336). See ../DISCREPANCY.md.
# Usage (from benchmark/dlinear/):
#   discrepancy/run_variant.sh <name> <code: current|may2022> <pred_len> <batch_size> <lr> <seed> [<seed> ...]
# DATA=ETTh2|ETTm1 switches the dataset (cross-checks only). Extra run_longExp.py arguments can be passed in $EXTRA (e.g. EXTRA="--patience 10 --train_epochs 30").
#   current = manual/LTSF-Linear (upstream 0c11366 + ltsf_linear_cpu_modern.patch)
#   may2022 = discrepancy/LTSF-Linear-721ab58 (upstream 721ab58, last commit before the 2022-08-15
#             "Update scripts and models" commit, + may2022_cpu_modern.patch: SEED env, threads, np.inf)
#   current_init1L = copy of manual/LTSF-Linear with the two commented-out 1/L weight-init lines of
#             models/DLinear.py (shared-layer branch) enabled (diff: init1L.diff)
# Each run writes results/logs/discrepancy_<name>_s<seed>.log and appends a row to
# results/discrepancy_etth1_720.csv.
set -euo pipefail
CASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$CASE_DIR/../../envs/dlinear/bin/python"
name=$1 code=$2 pred=$3 bs=$4 lr=$5; shift 5
EXTRA=${EXTRA:-}
DATA=${DATA:-ETTh1}   # cross-checks only; the experiment name then starts with xcheck_<DATA>
case $code in
  current) CODE_DIR="$CASE_DIR/manual/LTSF-Linear" ;;
  may2022) CODE_DIR="$CASE_DIR/discrepancy/LTSF-Linear-721ab58" ;;
  current_init1L) CODE_DIR="$CASE_DIR/discrepancy/LTSF-Linear-0c11366-init1L" ;;
  current_decoder) CODE_DIR="$CASE_DIR/discrepancy/LTSF-Linear-0c11366-decoder" ;;  # 2026-10-05: unused Linear_Decoder restored (RNG only)
  *) echo "unknown code $code"; exit 1 ;;
esac
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TORCH_NUM_THREADS=4
CSV="$CASE_DIR/results/discrepancy_etth1_720.csv"
[ -f "$CSV" ] || echo "experiment,code,pred_len,batch_size,lr,extra_args,seed,mse,mae,droplast_mse,test_windows,epochs_run,best_epoch,best_vali_loss,wall_s" > "$CSV"
cd "$CODE_DIR"
for seed in "$@"; do
  log="$CASE_DIR/results/logs/discrepancy_${name}_s${seed}.log"
  t0=$(python3 -c 'import time; print(time.time())')
  # shellcheck disable=SC2086
  SEED=$seed "$PY" -u run_longExp.py --is_training 1 --root_path ./dataset/ --data_path "$DATA.csv" \
    --model_id "${DATA}_336_${pred}" --model DLinear --data "$DATA" --features M \
    --seq_len 336 --pred_len "$pred" --enc_in 7 --des Exp --itr 1 \
    --batch_size "$bs" --learning_rate "$lr" --num_workers 0 \
    --checkpoints "./checkpoints_disc/${name}/" $EXTRA > "$log" 2>&1
  t1=$(python3 -c 'import time; print(time.time())')
  wall=$(python3 -c "print(round($t1-$t0,1))")
  echo "wall_clock_s:$wall" >> "$log"
  python3 - "$log" "$name" "$code" "$pred" "$bs" "$lr" "$EXTRA" "$seed" "$wall" >> "$CSV" <<'EOF'
import re, sys
log, *meta = sys.argv[1:]
t = open(log).read()
mse, mae = re.findall(r"^mse:([0-9.eE+-]+), mae:([0-9.eE+-]+)", t, re.M)[-1]
d = re.findall(r"^droplast_mse:([0-9.eE+-]+)", t, re.M)
dmse = d[-1] if d else mse          # may2022 code already uses drop_last=True for the test loader
w = re.findall(r"^test_windows:(\d+)", t, re.M)
nwin = w[-1] if w else ""
vals = [float(v) for v in re.findall(r"^Epoch: \d+, Steps: \d+ \| Train Loss: \S+ Vali Loss: (\S+)", t, re.M)]
best = min(range(len(vals)), key=vals.__getitem__)
name, code, pred, bs, lr, extra, seed, wall = meta
print(",".join([name, code, pred, bs, lr, '"%s"' % extra, seed, mse, mae, dmse, nwin, str(len(vals)), str(best + 1), "%.7f" % vals[best], wall]))
EOF
  tail -1 "$CSV"
done
