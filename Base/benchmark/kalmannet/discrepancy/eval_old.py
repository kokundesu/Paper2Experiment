"""[p2e] Table VI (Lorenz, spherical observations h_nonlinear, nu=0 dB) evaluation on the OLD code
(architecture-#2 branch @ 5bce6e8, the C4 code base of Jan 2022, closest to the paper's v3 / TSP version).

The old branches contain no script for Table VI, so this driver wires old-code components the way the
old scripts do (main_lorenz.py@fe71ad7: SystemModel(f, q, h_nonlinear, r, ...), EKFTest(sys_model, ...);
Pipeline_EKF.NNTest for KalmanNet):
  KalmanNet_sysmdl.SystemModel (data), EKF_test.EKFTest / EKF.ExtendedKalmanFilter (mode 'full'),
  KalmanNet_nn.KalmanNetNN (arch #2), Simulations/Lorenz_Atractor/{parameters,model}.py.
Run from manual/KalmanNet_TSP_old:  ../../../../envs/kalmannet/bin/python ../../discrepancy/eval_old.py
Env vars:
  SEED=0  INV_R2_DB=30  NU_DB=0  T=20  N_T=200
  DATA = fixed     -> every sequence starts at m1x_0=(1,1,1) (old and new code default)
         attractor -> T-step windows chopped from long (LONG_T=2000) trajectories started at (1,1,1)
  INIT = m1x_0 (filter starts at (1,1,1), as the old code does) | true (filter starts at the true x_0)
  JAC  = old (as released: EKF obs. Jacobian = getJacobian(x,'ObsAcc') = Jacobian of the LINEAR h = I)
         correct ([ablation] Jacobian of h_nonlinear)
  QF_SCALE = 1 -> the EKF is given Q_filter = QF_SCALE * Q_true ([ablation] 0 = zero Kalman gain, since P0 = 0)
  KNET = path to a pickled old KalmanNet model to evaluate as well (e.g. the authors' Dec-2021
         model_KNetNew_DT_HNL_r30q30_T20.pt); empty = EKF only
"""
import os, sys, random, math
sys.path.insert(0, os.getcwd())  # old code imports are relative to the repo root
import numpy as np
import torch
SEED = int(os.environ.get('SEED', 0))
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)
torch.set_num_threads(int(os.environ.get('OMP_NUM_THREADS', 4)))
from filing_paths import path_model
sys.path.insert(1, path_model)
from parameters import m1x_0, m2x_0, m, n
import model
from model import f, h, h_nonlinear
from KalmanNet_sysmdl import SystemModel
import EKF as EKF_module
from EKF_test import EKFTest

E = os.environ.get
INV_R2_DB = float(E('INV_R2_DB', 30)); NU_DB = float(E('NU_DB', 0)); T = int(E('T', 20)); N_T = int(E('N_T', 200))
DATA = E('DATA', 'fixed'); INIT = E('INIT', 'm1x_0'); JAC = E('JAC', 'old'); QF_SCALE = float(E('QF_SCALE', 1)); KNET = E('KNET', ''); LONG_T = int(E('LONG_T', 2000))
r2 = 10 ** (-INV_R2_DB / 10); q2 = 10 ** (NU_DB / 10) * r2
print(f"SEED: {SEED}  1/r2 [dB]: {INV_R2_DB}  nu [dB]: {NU_DB}  T: {T}  N_T: {N_T}  DATA: {DATA}  INIT: {INIT}  JAC: {JAC}  QF_SCALE: {QF_SCALE}  KNET: {KNET}")
print("m1x_0:", m1x_0.flatten().tolist(), " m2x_0 diag:", torch.diag(m2x_0).tolist())

if JAC == 'correct':
    _orig = model.getJacobian
    def _getJacobian(x, a):
        if a == 'ObsAcc':
            y = torch.reshape(x.T, [x.size()[0]]) if x.dim() > 1 else x
            return torch.autograd.functional.jacobian(h_nonlinear, y).view(-1, m)
        return _orig(x, a)
    EKF_module.getJacobian = _getJacobian
print("EKF obs. Jacobian at x=(1,1,1):", [[round(v, 3) for v in row] for row in EKF_module.getJacobian(torch.ones(3), 'ObsAcc').tolist()])

Q = q2 * torch.eye(m); R = r2 * torch.eye(n)
sys_model = SystemModel(f, Q, h_nonlinear, R, T, T)
sys_model.InitSequence(m1x_0, m2x_0)
if DATA == 'fixed':
    sys_model.GenerateBatch(N_T, T, randomInit=False)
    test_input, test_target = sys_model.Input, sys_model.Target
    x0s = m1x_0.view(1, m).repeat(N_T, 1)
else:
    per = LONG_T // (T + 1) - 1
    n_long = math.ceil(N_T / per)
    sys_model.GenerateBatch(n_long, LONG_T, randomInit=False)
    xs, ys, x0l = [], [], []
    for i in range(n_long):
        for k in range(per):
            s = k * (T + 1)
            x0l.append(sys_model.Target[i, :, s]); xs.append(sys_model.Target[i, :, s + 1:s + 1 + T]); ys.append(sys_model.Input[i, :, s + 1:s + 1 + T])
    test_target = torch.stack(xs)[:N_T]; test_input = torch.stack(ys)[:N_T]; x0s = torch.stack(x0l)[:N_T]
    sys_model.InitSequence(m1x_0, m2x_0)

def report(name, arr):
    fin = torch.isfinite(arr)
    dB = 10 * torch.log10(arr[fin].mean()).item() if fin.any() else float('nan')
    print(f"RESULT {name}: dB_of_mean={dB:.3f} mean_of_dB={(10*torch.log10(arr[fin])).mean().item():.3f} "
          f"median_dB={10*torch.log10(arr[fin].median()).item():.3f} n_nonfinite={int((~fin).sum())}")
    return dB

filt_model = sys_model
if QF_SCALE != 1:
    filt_model = SystemModel(f, QF_SCALE * Q, h_nonlinear, R, T, T); filt_model.InitSequence(m1x_0, m2x_0)
if INIT == 'm1x_0' and DATA == 'fixed':
    [arr, avg, dB, KG, out] = EKFTest(filt_model, test_input, test_target)  # exactly the old test routine
    print("max |K| over test set:", KG.abs().max().item())
else:  # per-sequence init: same EKF class, init at the true x_0 (or m1x_0)
    ekf = EKF_module.ExtendedKalmanFilter(filt_model, 'full')
    arr = torch.empty(N_T); lf = torch.nn.MSELoss(reduction='mean')
    for j in range(N_T):
        ekf.InitSequence(x0s[j] if INIT == 'true' else m1x_0, m2x_0)
        ekf.GenerateSequence(test_input[j], T)
        arr[j] = lf(ekf.x, test_target[j]).item()
dB = report('EKF', arr)
print("Extended Kalman Filter - MSE LOSS: tensor(%.4f) [dB]" % dB)

if KNET:
    knet = torch.load(KNET, map_location='cpu', weights_only=False)
    knet.eval()
    arrk = torch.empty(N_T); lf = torch.nn.MSELoss(reduction='mean')
    with torch.no_grad():
        for j in range(N_T):  # mirrors Pipeline_EKF.NNTest of the old code
            knet.InitSequence((x0s[j].view(m, 1) if INIT == 'true' else m1x_0), T)
            xo = torch.empty(m, T)
            for t in range(T):
                xo[:, t] = knet(test_input[j, :, t])
            arrk[j] = lf(xo, test_target[j]).item()
    dBk = report('KalmanNet(pretrained)', arrk)
    print("KalmanNet-MSE Test: tensor(%.4f) [dB]" % dBk)
