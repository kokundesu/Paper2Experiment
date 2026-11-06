"""Run the repo's main_lor_DT_NLobs.py (patched copy) with one extra override, without editing it.
Run from manual/KalmanNet_TSP. Env: SEED, RUN_TAG, INV_R2_DB (handled by the script itself) and
  COMPOSITION_LOSS = 1 (repo default: CompositionLoss=True, alpha=0.5) | 0 (paper eq. 10/13: pure state MSE)
"""
import os, re, sys
sys.path.insert(0, os.getcwd())
src = open('main_lor_DT_NLobs.py').read()
cl = os.environ.get('COMPOSITION_LOSS', '1') == '1'
src, k = re.subn(r'args\.CompositionLoss = True', f'args.CompositionLoss = {cl}', src)
assert k == 1, 'pattern not found'
print(f"[discrepancy] CompositionLoss override -> {cl}")
sys.argv = ['main_lor_DT_NLobs.py']
exec(compile(src, 'main_lor_DT_NLobs.py', 'exec'), {'__name__': '__main__'})
