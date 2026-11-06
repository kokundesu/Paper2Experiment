#!/usr/bin/env bash
# EKF-only experiments for DISCREPANCY.md (seconds each). Run from benchmark/kalmannet/:
#   bash discrepancy/run_ekf_ablations.sh
# Every run's stdout is appended to results/logs/discrepancy_<name>.log, preceded by a "RUN ..." header line;
# discrepancy/summarize.py turns the logs into results/discrepancy_ablation.csv.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=$ROOT/../../envs/kalmannet/bin/python
LOG=$ROOT/results/logs
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4} MKL_NUM_THREADS=${OMP_NUM_THREADS:-4}
ALL="-10 0 10 20 30"; TWO="30 10"; SEEDS="0 1 2"

main_run() {  # name levels options...
  local name=$1 levels=$2; shift 2
  local f=$LOG/discrepancy_$name.log; : > "$f"
  for db in $levels; do for s in $SEEDS; do
    echo "RUN name=$name code=main inv_r2_db=$db seed=$s opts=[$*]" >> "$f"
    (cd "$ROOT/manual/KalmanNet_TSP" && $PY ../../discrepancy/ekf_ablation_main.py --inv_r2_db "$db" --seed "$s" --tag "$name" "$@") >> "$f" 2>&1
  done; done
  echo "$name: $(grep -c '^RESULT' "$f") runs"
}
old_run() {  # name levels VAR=value...
  local name=$1 levels=$2; shift 2
  local f=$LOG/discrepancy_$name.log; : > "$f"
  for db in $levels; do for s in $SEEDS; do
    local extra=()
    if [[ -n "${KNET_BY_DB:-}" ]]; then extra=(KNET=../scratch_old/model_KNetNew_DT_HNL_r${db}q${db}_T20.pt); fi
    echo "RUN name=$name code=old inv_r2_db=$db seed=$s opts=[$* ${extra[*]+${extra[*]}}]" >> "$f"
    (cd "$ROOT/manual/KalmanNet_TSP_old" && env SEED="$s" INV_R2_DB="$db" "$@" ${extra[@]+"${extra[@]}"} $PY ../../discrepancy/eval_old.py) >> "$f" 2>&1
  done; done
  echo "$name: $(grep -c '^RESULT EKF' "$f") runs"
}

# PART=main|old|qgrid|all (default all)
PART=${PART:-all}
if [[ $PART == main || $PART == all ]]; then
# ---------------- current code (main @ 828a2cf + CPU/Jacobian fixes) ----------------
main_run main_baseline            "$ALL"                                  # repo defaults: x0=(1,1,1) known, P0=0, true Q/R
main_run main_zero_gain_Q0        "$ALL" --q_scale 0                      # EKF told Q=0 (with P0=0 -> K=0: open loop)
main_run main_zero_gain_Rinf      "$ALL" --r_scale 1e6                    # EKF told R x1e6 (-> K~0)
main_run main_q_x0.001            "$TWO" --q_scale 0.001
main_run main_q_x0.01             "$TWO" --q_scale 0.01
main_run main_q_x100              "$TWO" --q_scale 100
main_run main_q_x1000             "$TWO" --q_scale 1000
main_run main_P0_1                "$TWO" --P0 1
main_run main_P0_100              "$TWO" --P0 100
main_run main_unknown_x0_attractor "$TWO" --data attractor                # windows on the attractor, EKF still starts at (1,1,1), P0=0
main_run main_unknown_x0_attractor_P0_100 "$TWO" --data attractor --P0 100
main_run main_attractor_known_x0  "$TWO" --data attractor --ekf_init true
main_run main_unknown_x0_uniform100 "$TWO" --data randinit_uniform        # repo randomInit option (x0 ~ U[0,100)^3)
main_run main_unknown_x0_normal_var1 "$TWO" --data randinit_normal --init_var 1
main_run main_T200                "$TWO" --T 200
main_run main_T2000               "$TWO" --T 2000 --N_T 100
main_run main_hjac_identity       "$TWO" --h_jac identity                 # emulates the pre-2023 EKF Jacobian bug
main_run main_nu_plus20dB         "$TWO" --nu_db 20
SEEDS="0" main_run main_zero_gain_Q0_NT1000 "$ALL" --q_scale 0 --N_T 1000

fi
if [[ $PART == old || $PART == all ]]; then
# ---------------- old code (architecture-#2 branch @ 5bce6e8, Jan 2022) ----------------
old_run old_as_released           "$ALL" JAC=old                          # EKF Jacobian = I (bug), x0=(1,1,1), P0=0, true Q/R
old_run old_correct_jacobian      "$ALL" JAC=correct
old_run old_zero_gain_Q0          "$ALL" JAC=old QF_SCALE=0
KNET_BY_DB=1 old_run old_authors_knet_ckpt "30 20 -10" JAC=old         # authors' Dec-2021 HNL checkpoints (r30q30, r20q20, r-10q-10, T20)
KNET_BY_DB=1 old_run old_authors_knet_ckpt_attractor_known_x0 "30 20" JAC=correct DATA=attractor INIT=true
fi
if [[ $PART == qgrid || $PART == all ]]; then
# Q grid for the old, as-released EKF (Jacobian bug): what does shrinking the filter's Q do? (seed 0 only)
for qs in 0.1 0.01 0.001 0.0001 0.000001; do SEEDS=0 old_run old_as_released_qgrid_$qs "$ALL" JAC=old QF_SCALE=$qs; done
fi
