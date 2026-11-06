"""Parse results/logs/discrepancy_*.log into results/discrepancy_ablation.csv and print a mean+-std table.
Run from benchmark/kalmannet/:  ../../envs/kalmannet/bin/python discrepancy/summarize.py"""
import csv, glob, re, statistics as st
from collections import defaultdict
PAPER_EKF = {-10: 26.38, 0: 21.78, 10: 14.50, 20: 4.84, 30: -4.02}
PAPER_KNET = {-10: 14.55, 0: 6.77, 10: -1.77, 20: -10.57, 30: -15.24}
rows = []
for f in sorted(glob.glob('results/logs/discrepancy_*.log')):
    cur = None
    for line in open(f):
        m = re.match(r'RUN name=(\S+) code=(\S+) inv_r2_db=(\S+) seed=(\S+) opts=\[(.*)\]', line)
        if m:
            cur = dict(name=m[1], code=m[2], inv_r2_db=int(float(m[3])), seed=int(m[4]), options=m[5].strip(),
                       metric_source='', ekf_dB='', ekf_mean_of_dB='', ekf_median_dB='', ekf_n_nonfinite='',
                       knet_dB='', knet_mean_of_dB='', knet_median_dB='', log=f.split('/')[-1])
            rows.append(cur); continue
        if cur is None: continue
        m = re.match(r'RESULT tag=\S* inv_r2_db=\S+ seed=\S+ ekf_dB=(\S+) mean_of_dB=(\S+) median_dB=(\S+) n_nonfinite=(\d+)', line)
        if m: cur.update(ekf_dB=m[1], ekf_mean_of_dB=m[2], ekf_median_dB=m[3], ekf_n_nonfinite=m[4])
        m = re.match(r'RESULT EKF: dB_of_mean=(\S+) mean_of_dB=(\S+) median_dB=(\S+) n_nonfinite=(\d+)', line)
        if m: cur.update(ekf_dB=m[1], ekf_mean_of_dB=m[2], ekf_median_dB=m[3], ekf_n_nonfinite=m[4])
        m = re.match(r'RESULT KalmanNet\S*: dB_of_mean=(\S+) mean_of_dB=(\S+) median_dB=(\S+)', line)
        if m: cur.update(knet_dB=m[1], knet_mean_of_dB=m[2], knet_median_dB=m[3])
        m = re.search(r'KalmanNet-MSE Test: tensor\((-?[0-9.]+)\) \[dB\]', line)  # training runs (repo output)
        if m and not cur['knet_dB']: cur.update(knet_dB=m[1])
        m = re.search(r'Extended Kalman Filter - MSE LOSS: tensor\((-?[0-9.naif]+)\) \[dB\]', line)
        if m and not cur['ekf_dB']: cur.update(ekf_dB=m[1])
for r in rows:
    r['paper_ekf_dB'] = PAPER_EKF.get(r['inv_r2_db'], ''); r['paper_knet_dB'] = PAPER_KNET.get(r['inv_r2_db'], '')
keys = ['name', 'code', 'inv_r2_db', 'seed', 'options', 'ekf_dB', 'ekf_mean_of_dB', 'ekf_median_dB', 'ekf_n_nonfinite',
        'knet_dB', 'knet_mean_of_dB', 'knet_median_dB', 'paper_ekf_dB', 'paper_knet_dB', 'log']
with open('results/discrepancy_ablation.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=keys, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
print(f"wrote results/discrepancy_ablation.csv ({len(rows)} runs)")

def agg(vals):
    v = [float(x) for x in vals if x not in ('', 'nan') and abs(float(x)) < 1e3]
    bad = len(vals) - len(v)
    if not v: return 'nan'
    s = f"{st.mean(v):.2f}" + (f" ± {st.stdev(v):.2f}" if len(v) > 1 else '')
    return s + (f" ({bad} nan/overflow)" if bad else '')
g = defaultdict(list)
for r in rows: g[(r['name'], r['inv_r2_db'])].append(r)
print(f"{'name':42s} {'1/r2':>5s} {'EKF dB (mean of seeds)':>28s} {'median-seq dB':>16s} {'KNet dB':>16s} {'paper EKF':>9s} {'paper KNet':>10s}")
for (name, db), rs in g.items():
    print(f"{name:42s} {db:5d} {agg([r['ekf_dB'] for r in rs]):>28s} {agg([r['ekf_median_dB'] for r in rs]):>16s} "
          f"{agg([r['knet_dB'] for r in rs]):>16s} {PAPER_EKF.get(db, ''):>9} {PAPER_KNET.get(db, ''):>10}")
