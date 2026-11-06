"""
@author: Maziar Raissi
"""

import sys
sys.path.insert(0, '../../Utilities/')

import os
import tensorflow.compat.v1 as tf  # PATCH: TF1 API on TF 2.x
tf.disable_v2_behavior()
import numpy as np
import scipy.optimize  # PATCH: replaces tf.contrib.opt.ScipyOptimizerInterface
import matplotlib.pyplot as plt
import scipy.io
from scipy.interpolate import griddata
from pyDOE import lhs
# from plotting import newfig, savefig  # PATCH: plotting disabled (plotting.py rcParams fail on matplotlib >= 3.x)
from mpl_toolkits.mplot3d import Axes3D
import time
import matplotlib.gridspec as gridspec
from mpl_toolkits.axes_grid1 import make_axes_locatable

SEED = int(os.environ.get('SEED', 1234))  # PATCH: seed configurable (original: 1234)
np.random.seed(SEED)
tf.set_random_seed(SEED)


class ScipyOptimizerInterface:
    """PATCH: drop-in replacement for tf.contrib.opt.ScipyOptimizerInterface (removed in TF2).
    Same mechanics: pack all trainable variables into one float64 vector, let
    scipy.optimize.minimize(method='L-BFGS-B', jac=True) drive the graph's loss
    and gradients, write the final vector back into the variables."""
    def __init__(self, loss, method='L-BFGS-B', options=None):
        self.loss = loss
        self.method = method
        self.options = options or {}
        self.vars = tf.trainable_variables()
        self.shapes = [v.shape.as_list() for v in self.vars]
        self.sizes = [int(np.prod(s)) for s in self.shapes]
        grads = tf.gradients(loss, self.vars)
        self.packed_grad = tf.concat([tf.reshape(g, [-1]) for g in grads], 0)
        self.packed_var = tf.concat([tf.reshape(v, [-1]) for v in self.vars], 0)
        self.phs = [tf.placeholder(v.dtype.base_dtype, shape=s) for v, s in zip(self.vars, self.shapes)]
        self.assign_op = tf.group(*[v.assign(p) for v, p in zip(self.vars, self.phs)])
        self.result = None

    def _assign(self, sess, x):
        offs = np.cumsum([0] + self.sizes)
        sess.run(self.assign_op, {p: x[offs[i]:offs[i+1]].reshape(self.shapes[i])
                                  for i, p in enumerate(self.phs)})

    def minimize(self, sess, feed_dict=None, fetches=None, loss_callback=None):
        fetches = fetches or []
        def fun(x):
            self._assign(sess, x)
            out = sess.run([self.loss, self.packed_grad] + fetches, feed_dict)
            if loss_callback is not None:
                loss_callback(*out[2:])
            return np.float64(out[0]), out[1].astype('float64')
        x0 = sess.run(self.packed_var).astype('float64')
        self.result = scipy.optimize.minimize(fun, x0, jac=True, method=self.method, options=self.options)
        self._assign(sess, self.result.x)
        return self.result

class PhysicsInformedNN:
    # Initialize the class
    def __init__(self, X_u, u, X_f, layers, lb, ub, nu):
        
        self.lb = lb
        self.ub = ub
    
        self.x_u = X_u[:,0:1]
        self.t_u = X_u[:,1:2]
        
        self.x_f = X_f[:,0:1]
        self.t_f = X_f[:,1:2]
        
        self.u = u
        
        self.layers = layers
        self.nu = nu
        
        # Initialize NNs
        self.weights, self.biases = self.initialize_NN(layers)
        
        # tf placeholders and graph
        self.sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True,
                                                     log_device_placement=False))
        
        self.x_u_tf = tf.placeholder(tf.float32, shape=[None, self.x_u.shape[1]])
        self.t_u_tf = tf.placeholder(tf.float32, shape=[None, self.t_u.shape[1]])        
        self.u_tf = tf.placeholder(tf.float32, shape=[None, self.u.shape[1]])
        
        self.x_f_tf = tf.placeholder(tf.float32, shape=[None, self.x_f.shape[1]])
        self.t_f_tf = tf.placeholder(tf.float32, shape=[None, self.t_f.shape[1]])        
                
        self.u_pred = self.net_u(self.x_u_tf, self.t_u_tf) 
        self.f_pred = self.net_f(self.x_f_tf, self.t_f_tf)         
        
        self.loss = tf.reduce_mean(tf.square(self.u_tf - self.u_pred)) + \
                    tf.reduce_mean(tf.square(self.f_pred))
               
                
        self.optimizer = ScipyOptimizerInterface(self.loss, 
                                                                method = 'L-BFGS-B', 
                                                                options = {'maxiter': MAXITER,  # PATCH: env-configurable, default 50000 as original
                                                                           'maxfun': MAXITER,
                                                                           'maxcor': 50,
                                                                           'maxls': 50,
                                                                           'ftol' : float(os.environ.get('FTOL', 1.0 * np.finfo(float).eps))})  # PATCH: env override for diagnostics only
        
        init = tf.global_variables_initializer()
        self.sess.run(init)

                
    def initialize_NN(self, layers):        
        weights = []
        biases = []
        num_layers = len(layers) 
        for l in range(0,num_layers-1):
            W = self.xavier_init(size=[layers[l], layers[l+1]])
            b = tf.Variable(tf.zeros([1,layers[l+1]], dtype=tf.float32), dtype=tf.float32)
            weights.append(W)
            biases.append(b)        
        return weights, biases
        
    def xavier_init(self, size):
        in_dim = size[0]
        out_dim = size[1]        
        xavier_stddev = np.sqrt(2/(in_dim + out_dim))
        return tf.Variable(tf.truncated_normal([in_dim, out_dim], stddev=xavier_stddev), dtype=tf.float32)
    
    def neural_net(self, X, weights, biases):
        num_layers = len(weights) + 1
        
        H = 2.0*(X - self.lb)/(self.ub - self.lb) - 1.0
        for l in range(0,num_layers-2):
            W = weights[l]
            b = biases[l]
            H = tf.tanh(tf.add(tf.matmul(H, W), b))
        W = weights[-1]
        b = biases[-1]
        Y = tf.add(tf.matmul(H, W), b)
        return Y
            
    def net_u(self, x, t):
        u = self.neural_net(tf.concat([x,t],1), self.weights, self.biases)
        return u
    
    def net_f(self, x,t):
        u = self.net_u(x,t)
        u_t = tf.gradients(u, t)[0]
        u_x = tf.gradients(u, x)[0]
        u_xx = tf.gradients(u_x, x)[0]
        f = u_t + u*u_x - self.nu*u_xx
        
        return f
    
    def callback(self, loss):
        # PATCH: print every 1000th evaluation only (original printed every evaluation)
        self.n_eval = getattr(self, 'n_eval', 0) + 1
        if self.n_eval % 1000 == 0:
            print('Eval %d Loss: %.3e' % (self.n_eval, loss), flush=True)
        
    def train(self):
        
        tf_dict = {self.x_u_tf: self.x_u, self.t_u_tf: self.t_u, self.u_tf: self.u,
                   self.x_f_tf: self.x_f, self.t_f_tf: self.t_f}
                                                                                                                          
        return self.optimizer.minimize(self.sess, 
                                feed_dict = tf_dict,         
                                fetches = [self.loss], 
                                loss_callback = self.callback)        
                                    
    
    def predict(self, X_star):
                
        u_star = self.sess.run(self.u_pred, {self.x_u_tf: X_star[:,0:1], self.t_u_tf: X_star[:,1:2]})  
        f_star = self.sess.run(self.f_pred, {self.x_f_tf: X_star[:,0:1], self.t_f_tf: X_star[:,1:2]})
               
        return u_star, f_star
    
MAXITER = int(os.environ.get('MAXITER', 50000))  # PATCH

if __name__ == "__main__": 
     
    nu = 0.01/np.pi
    noise = 0.0        

    # PATCH: env-configurable for table cells; defaults are the original values
    N_u = int(os.environ.get('N_U', 100))
    N_f = int(os.environ.get('N_F', 10000))
    n_hidden = int(os.environ.get('LAYERS', 8))
    n_neurons = int(os.environ.get('NEURONS', 20))
    layers = [2] + [n_neurons]*n_hidden + [1]   # default: [2, 20, 20, 20, 20, 20, 20, 20, 20, 1]
    
    data = scipy.io.loadmat('../Data/burgers_shock.mat')
    
    t = data['t'].flatten()[:,None]
    x = data['x'].flatten()[:,None]
    Exact = np.real(data['usol']).T
    
    X, T = np.meshgrid(x,t)
    
    X_star = np.hstack((X.flatten()[:,None], T.flatten()[:,None]))
    u_star = Exact.flatten()[:,None]              

    # Doman bounds
    lb = X_star.min(0)
    ub = X_star.max(0)    
        
    xx1 = np.hstack((X[0:1,:].T, T[0:1,:].T))
    uu1 = Exact[0:1,:].T
    xx2 = np.hstack((X[:,0:1], T[:,0:1]))
    uu2 = Exact[:,0:1]
    xx3 = np.hstack((X[:,-1:], T[:,-1:]))
    uu3 = Exact[:,-1:]
    
    X_u_train = np.vstack([xx1, xx2, xx3])
    X_f_train = lb + (ub-lb)*lhs(2, N_f)
    X_f_train = np.vstack((X_f_train, X_u_train))
    u_train = np.vstack([uu1, uu2, uu3])
    
    idx = np.random.choice(X_u_train.shape[0], N_u, replace=False)
    X_u_train = X_u_train[idx, :]
    u_train = u_train[idx,:]
        
    model = PhysicsInformedNN(X_u_train, u_train, X_f_train, layers, lb, ub, nu)
    
    start_time = time.time()                
    res = model.train()
    elapsed = time.time() - start_time                
    print('Training time: %.4f' % (elapsed))
    
    u_pred, f_pred = model.predict(X_star)
            
    error_u = np.linalg.norm(u_star-u_pred,2)/np.linalg.norm(u_star,2)
    print('Error u: %e' % (error_u))                     
    # PATCH: machine-readable summary + optional CSV append
    print('Optimizer: nit=%d nfev=%d status=%d msg=%s final_loss=%.3e' % (res.nit, res.nfev, res.status, res.message, res.fun))
    csv = os.environ.get('RESULTS_CSV')
    if csv:
        new = not os.path.exists(csv)
        with open(csv, 'a') as fh:
            if new:
                fh.write('N_u,N_f,layers,neurons,seed,maxiter,error_u,final_loss,nit,nfev,status,train_time_s\n')
            fh.write('%d,%d,%d,%d,%d,%d,%.6e,%.6e,%d,%d,%d,%.1f\n' % (N_u, N_f, n_hidden, n_neurons, SEED, MAXITER,
                     error_u, res.fun, res.nit, res.nfev, res.status, elapsed))
    if os.environ.get('PLOT', '0') != '1':  # PATCH: plotting disabled by default
        sys.exit(0)

    
    U_pred = griddata(X_star, u_pred.flatten(), (X, T), method='cubic')
    Error = np.abs(Exact - U_pred)
    
    
    ######################################################################
    ############################# Plotting ###############################
    ######################################################################    
    
    fig, ax = newfig(1.0, 1.1)
    ax.axis('off')
    
    ####### Row 0: u(t,x) ##################    
    gs0 = gridspec.GridSpec(1, 2)
    gs0.update(top=1-0.06, bottom=1-1/3, left=0.15, right=0.85, wspace=0)
    ax = plt.subplot(gs0[:, :])
    
    h = ax.imshow(U_pred.T, interpolation='nearest', cmap='rainbow', 
                  extent=[t.min(), t.max(), x.min(), x.max()], 
                  origin='lower', aspect='auto')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.05)
    fig.colorbar(h, cax=cax)
    
    ax.plot(X_u_train[:,1], X_u_train[:,0], 'kx', label = 'Data (%d points)' % (u_train.shape[0]), markersize = 4, clip_on = False)
    
    line = np.linspace(x.min(), x.max(), 2)[:,None]
    ax.plot(t[25]*np.ones((2,1)), line, 'w-', linewidth = 1)
    ax.plot(t[50]*np.ones((2,1)), line, 'w-', linewidth = 1)
    ax.plot(t[75]*np.ones((2,1)), line, 'w-', linewidth = 1)    
    
    ax.set_xlabel('$t$')
    ax.set_ylabel('$x$')
    ax.legend(frameon=False, loc = 'best')
    ax.set_title('$u(t,x)$', fontsize = 10)
    
    ####### Row 1: u(t,x) slices ##################    
    gs1 = gridspec.GridSpec(1, 3)
    gs1.update(top=1-1/3, bottom=0, left=0.1, right=0.9, wspace=0.5)
    
    ax = plt.subplot(gs1[0, 0])
    ax.plot(x,Exact[25,:], 'b-', linewidth = 2, label = 'Exact')       
    ax.plot(x,U_pred[25,:], 'r--', linewidth = 2, label = 'Prediction')
    ax.set_xlabel('$x$')
    ax.set_ylabel('$u(t,x)$')    
    ax.set_title('$t = 0.25$', fontsize = 10)
    ax.axis('square')
    ax.set_xlim([-1.1,1.1])
    ax.set_ylim([-1.1,1.1])
    
    ax = plt.subplot(gs1[0, 1])
    ax.plot(x,Exact[50,:], 'b-', linewidth = 2, label = 'Exact')       
    ax.plot(x,U_pred[50,:], 'r--', linewidth = 2, label = 'Prediction')
    ax.set_xlabel('$x$')
    ax.set_ylabel('$u(t,x)$')
    ax.axis('square')
    ax.set_xlim([-1.1,1.1])
    ax.set_ylim([-1.1,1.1])
    ax.set_title('$t = 0.50$', fontsize = 10)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.35), ncol=5, frameon=False)
    
    ax = plt.subplot(gs1[0, 2])
    ax.plot(x,Exact[75,:], 'b-', linewidth = 2, label = 'Exact')       
    ax.plot(x,U_pred[75,:], 'r--', linewidth = 2, label = 'Prediction')
    ax.set_xlabel('$x$')
    ax.set_ylabel('$u(t,x)$')
    ax.axis('square')
    ax.set_xlim([-1.1,1.1])
    ax.set_ylim([-1.1,1.1])    
    ax.set_title('$t = 0.75$', fontsize = 10)
    
    # savefig('./figures/Burgers')  
    



