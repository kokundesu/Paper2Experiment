"""Single-factor ablations of the Table VI EKF baseline on the CURRENT (main @ 828a2cf, patched) code.

Run from benchmark/kalmannet/manual/KalmanNet_TSP (the repo's imports are relative to it), e.g.
  ../../../../envs/kalmannet/bin/python ../../discrepancy/ekf_ablation_main.py --inv_r2_db 30 --data attractor
Uses only the repo's own components: Extended_sysmdl.SystemModel (data generation),
Simulations.utils.Short_Traj_Split (chopping long trajectories, the repo's `chop` path),
Filters.EKF.ExtendedKalmanFilter (batched EKF) and the repo's f / h_nonlinear.
Every option defaults to the repo default of main_lor_DT_NLobs.py.
"""
import argparse, os, random, sys, math
import numpy as np
import torch

p = argparse.ArgumentParser()
p.add_argument('--inv_r2_db', type=float, default=30.0)
p.add_argument('--nu_db', type=float, default=0.0)
p.add_argument('--seed', type=int, default=0)
p.add_argument('--N_T', type=int, default=200)
p.add_argument('--T', type=int, default=20)
p.add_argument('--data', default='fixed', choices=['fixed', 'attractor', 'randinit_uniform', 'randinit_normal'],
               help='fixed: every test sequence starts at m1x_0=(1,1,1) (repo default); '
                    'attractor: T-step windows chopped (Short_Traj_Split) from long trajectories started at (1,1,1); '
                    'randinit_uniform: x0 ~ U[0,variance)^3 (repo randomInit option, variance=100); '
                    'randinit_normal: x0 ~ N((1,1,1), init_var*I)')
p.add_argument('--long_T', type=int, default=2000, help='length of long trajectories for --data attractor')
p.add_argument('--burn', type=int, default=0, help='drop the first windows covering this many steps (attractor)')
p.add_argument('--init_var', type=float, default=100.0)
p.add_argument('--ekf_init', default='m1x_0', choices=['m1x_0', 'true'],
               help='m1x_0: EKF starts at the repo m1x_0=(1,1,1) (repo default); true: EKF starts at the true x_0 of each sequence')
p.add_argument('--P0', type=float, default=0.0, help='EKF initial covariance P0 = P0*I (repo default 0)')
p.add_argument('--q_scale', type=float, default=1.0, help='EKF uses Q_filter = q_scale * Q_true')
p.add_argument('--r_scale', type=float, default=1.0, help='EKF uses R_filter = r_scale * R_true')
p.add_argument('--h_jac', default='correct', choices=['correct', 'identity'],
               help='identity = emulate the pre-2023 code, whose EKF always used the Jacobian of the LINEAR h (=I)')
p.add_argument('--tag', default='')
a = p.parse_args()

random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
torch.set_num_threads(int(os.environ.get('OMP_NUM_THREADS', 4)))
sys.path.insert(0, os.getcwd())
from Simulations.Extended_sysmdl import SystemModel
from Simulations.utils import Short_Traj_Split
from Simulations.Lorenz_Atractor.parameters import m1x_0, m2x_0, m, n, f, h_nonlinear, Q_structure, R_structure
import Filters.EKF as EKFmod
from Filters.EKF import ExtendedKalmanFilter

class Args:  # what GenerateBatch / EKF read from args
    use_cuda = False; randomLength = False; distribution = 'uniform'; variance = 100.0
gargs = Args()

r2 = 10 ** (-a.inv_r2_db / 10); q2 = 10 ** (a.nu_db / 10) * r2
Q = q2 * Q_structure; R = r2 * R_structure
gen = SystemModel(f, Q, h_nonlinear, R, a.T, a.T, m, n)
gen.InitSequence(m1x_0, m2x_0)

if a.data == 'fixed':
    gen.GenerateBatch(gargs, a.N_T, a.T, randomInit=False)
    y, x = gen.Input, gen.Target
    x0 = m1x_0.view(1, m, 1).expand(a.N_T, -1, -1).clone()
elif a.data == 'attractor':
    per = a.long_T // (a.T + 1) - 1  # Short_Traj_Split drops the last (possibly partial) window
    skip = math.ceil(a.burn / (a.T + 1))
    n_long = math.ceil(a.N_T / (per - skip))
    gen.GenerateBatch(gargs, n_long, a.long_T, randomInit=False)
    xs, ys, inits = [], [], []
    for i in range(n_long):  # chop each long trajectory separately so the burn-in can be dropped per trajectory
        tgt, inp, ini = Short_Traj_Split(gen.Target[i:i+1], gen.Input[i:i+1], a.T)
        xs.append(tgt[skip:]); ys.append(inp[skip:]); inits.append(ini[skip:])
    x = torch.cat(xs)[:a.N_T]; y = torch.cat(ys)[:a.N_T]; x0 = torch.cat(inits)[:a.N_T].unsqueeze(-1)
elif a.data == 'randinit_uniform':
    gen.GenerateBatch(gargs, a.N_T, a.T, randomInit=True)
    y, x = gen.Input, gen.Target; x0 = gen.m1x_0_batch.clone()
else:
    gen.InitSequence(m1x_0, a.init_var * torch.eye(m))
    gargs.distribution = 'normal'
    gen.GenerateBatch(gargs, a.N_T, a.T, randomInit=True)
    y, x = gen.Input, gen.Target; x0 = gen.m1x_0_batch.clone()

# ---- filter model (what the EKF is told) ----
filt = SystemModel(f, a.q_scale * Q, h_nonlinear, a.r_scale * R, a.T, a.T, m, n)
if a.h_jac == 'identity':
    _orig = EKFmod.getJacobian
    def _gj(xx, g):
        if g is h_nonlinear:
            return torch.eye(n, m).reshape(1, n, m).repeat(xx.shape[0], 1, 1)
        return _orig(xx, g)
    EKFmod.getJacobian = _gj
ekf = ExtendedKalmanFilter(filt, gargs)
init_mean = x0 if a.ekf_init == 'true' else m1x_0.view(1, m, 1).expand(a.N_T, -1, -1)
ekf.Init_batched_sequence(init_mean.clone(), (a.P0 * torch.eye(m)).view(1, m, m).expand(a.N_T, -1, -1).clone())
ekf.GenerateBatch(y)
err = ((ekf.x - x) ** 2).mean(dim=(1, 2))  # per-sequence MSE over all 3 states and T steps (= repo loss_fn)
finite = torch.isfinite(err)
dB_of_mean = 10 * torch.log10(err[finite].mean()).item() if finite.any() else float('nan')
mean_of_dB = (10 * torch.log10(err[finite])).mean().item() if finite.any() else float('nan')
med = 10 * torch.log10(err[finite].median()).item() if finite.any() else float('nan')
kmax = ekf.KG_array.abs().max().item()
rho0 = x0.squeeze(-1).norm(dim=1).mean().item(); rho = x.norm(dim=1).mean().item()
print(f"CONFIG {vars(a)}")
print(f"data: x0 mean |x0| = {rho0:.2f}, mean |x_t| over test set = {rho:.2f}, test shape {tuple(x.shape)}")
print(f"Extended Kalman Filter - MSE LOSS: tensor({dB_of_mean:.4f}) [dB]")
print(f"RESULT tag={a.tag} inv_r2_db={a.inv_r2_db} seed={a.seed} ekf_dB={dB_of_mean:.3f} mean_of_dB={mean_of_dB:.3f} "
      f"median_dB={med:.3f} n_nonfinite={int((~finite).sum())} mean_rho={rho:.2f} max_abs_K={kmax:.3g}")
