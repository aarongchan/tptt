"""
Synthetic classification task (Task A)
Network trained using Stochastic Target Propagation Through Time (STPTT)

(C) 2022 Nikolay Manchev
This work is licensed under a Creative Commons Attribution-NonCommercial 4.0 International License.

This code supplements the paper Manchev, N. and Spratling, M., "Learning Multi-Modal Recurrent Neural Networks with Target Propagation"

"""

import torch
import sys
import torch.nn as nn
import numpy as np

import pandas as pd

from torch.nn.parameter import Parameter
from torch.autograd import Variable
from torch import optim
from tempOrder import TempOrderTask
from collections import OrderedDict

#from task_a import TaskAClass
import matplotlib.pyplot as plt

from sklearn.preprocessing import OneHotEncoder 
device = torch.device("cpu")
# cuda_ = "cuda:0"
# device = torch.device(cuda_ if torch.cuda.is_available() else "cpu")
# print(device)
# print(torch.cuda.is_available())
# print(torch.cuda.current_device())
# print(torch.cuda.get_device_name(0))

np.set_printoptions(precision=10, threshold=sys.maxsize, suppress=True)

class SRNN(object):

    def __init__(self, X, y, X_test, y_test, seq_length, n_hid, init, stochastic, hybrid, last_layer,
                 noise, batch_size, M, rng):
        super(SRNN, self).__init__()

        self.n_inp = X.shape[2]  # [seq size n_inp]
        self.n_out = y.shape[1]  # [size n_out]
        #breakpoint()
        self.M = M

        self.X = Variable(torch.from_numpy(X))
        self.y = Variable(torch.from_numpy(y))
        self.X_test = Variable(torch.from_numpy(X_test))
        self.y_test = Variable(torch.from_numpy(y_test))

        self.seq_length = seq_length
        self.n_hid = n_hid
        self.stochastic = stochastic
        self.hybrid = hybrid
        self.noise = noise
        self.last_layer = last_layer
        self.batch_size = batch_size
        self.rng = rng

        # assert seq_length >= 10, "seq_length must be at least 10"
        
        self.h0 = torch.zeros(self.batch_size, self.n_hid)

        self.Wxh = Parameter(init(torch.empty(self.n_inp, self.n_hid)))
        self.Whh = Parameter(init(torch.empty(self.n_hid, self.n_hid)))
        self.Why = Parameter(init(torch.empty(self.n_hid, self.n_out)))
        # self.Wxh = nn.Parameter(self.rand_ortho((n_hid, self.n_inp), np.sqrt(6./(self.n_inp + n_hid))).T)
        # self.Whh = nn.Parameter(self.rand_ortho((n_hid, n_hid), np.sqrt(6./(n_hid + n_hid))))
        # self.Why = nn.Parameter(self.rand_ortho((n_hid, self.n_out), np.sqrt(6./(n_hid + self.n_out))))
        self.bh = Parameter(torch.zeros(self.n_hid))
        self.by = Parameter(torch.zeros(self.n_out))

        self.Vhh = Parameter(init(torch.empty(self.n_hid, self.n_hid)))
        #self.Vhh = nn.Parameter(self.rand_ortho((n_hid, n_hid), np.sqrt(6./(n_hid + n_hid))))
        self.ch = Parameter(torch.zeros(self.n_hid))

        self.activ = torch.tanh#torch.sigmoid
        self.sftmx = nn.Softmax(dim=1)
        self.params = OrderedDict()

        self.params["Wxh"] = self.Wxh
        self.params["Whh"] = self.Whh
        self.params["Why"] = self.Why
        self.params["bh"] = self.bh
        self.params["by"] = self.by
        self.params["Vhh"] = self.Vhh
        self.params["ch"] = self.ch

    def rand_ortho(self, shape, irange):
        """
        Generates an orthogonal matrix. Original code from

        Lee, D. H. and Zhang, S. and Fischer, A. and Bengio, Y., Difference
        Target Propagation, CoRR, abs/1412.7525, 2014

        https://github.com/donghyunlee/dtp

        Parameters
        ----------
        shape  : matrix shape
        irange : range for the matrix elements
        rng    : RandomState instance, initiated with a seed

        Returns
        -------
        An orthogonal matrix of size *shape*
        """
        A = -irange + (2 * irange * torch.rand(*shape))
        U, _, V = torch.svd(A)
        return torch.mm(U, torch.mm(torch.eye(U.shape[1], V.shape[0]), V))

    def _sample(self, x):
        rand = torch.rand(size=x.shape)
        if self.hybrid:            
            ret = x
            #ret[:,0:x.shape[1]//2] = (rand[:,0:ret.shape[1]//2] < x[:,0:ret.shape[1]//2]).float()
            ret[0:x.shape[0]//2,:] = (rand[0:ret.shape[0]//2,:] < x[0:ret.shape[0]//2,:]).float()
        else:
            ret = (rand < x).type(torch.FloatTensor)
        return ret


    def _f(self, x, hs):
        if self.stochastic:
            hs = self._sample(hs)
        z = self.activ(hs @ self.Whh + x @ self.Wxh + self.bh)
        return z
    def _f_np(self, x, hs):
        def relu(x):
            return np.maximum(x, 0)
        
        if self.stochastic:
            hs = self._sample(hs)
        z = np.tanh(hs @ self.Whh.detach().numpy() + x @ self.Wxh.detach().numpy() + self.bh.detach().numpy())
        return z


    def _g(self, x, hs):
        return self.activ(hs @ self.Vhh + x @ self.Wxh + self.ch)
    def _g_np(self, x, hs):
        def relu(x):
            return np.maximum(x, 0)
        return np.tanh(hs @ self.Vhh.detach().numpy() + x @ self.Wxh.detach().numpy() + self.ch.detach().numpy())



    def _hidden(self, x):
        h = torch.empty(self.seq_length, self.batch_size, self.n_hid)
        h[0, :, :] = self._f(x[0, :, :], self.h0)

        for t in range(1, self.seq_length):
            h[t, :, :] = self._f(x[t, :, :], h[t - 1].clone())
        return h


    def _parameters(self):
        for key, value in self.params.items():
            yield value


    def _zero_grads(self):
        for p in self._parameters():
            if p.grad is not None:
                p.grad.detach_()
                p.grad.zero_()


    @staticmethod
    def _cross_entropy(y_hat, y):
        return torch.mean(torch.sum(-y * torch.log(y_hat), 1))

    @staticmethod
    def _mse(x, y):
        return torch.mean((x - y) ** 2)


    def _gaussian(self, x):
        return torch.randn(size=x.shape) * self.noise


    def _get_targets(self, x, hs_tmax, h, cost, ilr, error):
        h_ = torch.zeros(self.seq_length, self.batch_size, self.n_hid)
        #h_[-1, :, :] = hs_tmax - ilr * torch.autograd.grad(cost, hs_tmax, retain_graph=True)[0]
        z = np.dot(error, (self.Why.detach().numpy()).T)/h.shape[1]
        h_[-1, :, :] = hs_tmax - ilr * torch.from_numpy(z)
        h_[-1, :, :] = h[-1, :, :] - hs_tmax + h_[-1, :, :]

        for t in range(self.seq_length - 2, -1, -1):
            h_[t] = h[t] - self._g(x[t + 1, :, :], h[t + 1]) + self._g(x[t + 1, :, :], h_[t + 1].detach())

        return h_


    def _calc_g_grads(self, x, h):

        dVhh = torch.zeros((self.seq_length, self.n_hid, self.n_hid), requires_grad=False)
        dch = torch.zeros((self.seq_length, self.n_hid), requires_grad=False)
        grad_dVhh = torch.zeros((self.seq_length, self.n_hid, self.n_hid), requires_grad=False).detach().numpy()
        grad_dch = torch.zeros((self.seq_length, self.n_hid), requires_grad=False).detach().numpy()
        def targets_grads(h, x):
            per = h.shape[1]
            noise_shape = np.shape(h)
            noise = np.random.normal(0, .001, noise_shape)
            # noise = 0
            # def dot_sigmoid(W, b, h_prev):
            #     import math

            #     def sigmoid(x):
            #         return 1 / (1 + math.exp(-x))
            #     # W += add_gaussian_noise(W, std = 0.01)
            #     return sigmoid(np.dot(W, h_prev) + b)
            hp_with_noise_in_h = self._f_np(x, h.detach().numpy()+noise)#dot_sigmoid(F, f, h + noise)
            h_cap_with_noise = self._g_np(x, hp_with_noise_in_h)#dot_sigmoid(G, g, hp_with_noise_in_h)
            h_cap_error =  h_cap_with_noise - (h.detach().numpy()+noise)     # predictions - truth
            def relu_derivative(x):
                # return (x>0)*1-(x<=0)*0.01
                return (x>0)*1
                pass
            def tanh_derivative(x):
                return 1 - np.tanh(x)**2
            grad_G = np.dot((2 * h_cap_error * tanh_derivative(h_cap_with_noise)).T, hp_with_noise_in_h).T/per
            grad_g = np.sum(2 * h_cap_error * tanh_derivative(h_cap_with_noise), axis=0, keepdims=True)/per
            # grad_F = np.dot((2 * hp_error * relu_derivative(hp)).T, h).T/pers
            # grad_f = np.sum(2 * hp_error * relu_derivative(hp), axis=0, keepdims=True)/pers
            return grad_G, grad_g
        
        for t in range(1, len(h)):
            dVhh[t], dch[t] = torch.autograd.grad(self._mse(self._g(x[t, :, :], h[t]), h[t - 1].detach()),
                                                  (self.Vhh, self.ch), retain_graph=True)
            grad_dVhh[t], grad_dch[t] = targets_grads(h[t], x[t, :, :].detach().numpy())
        self.Vhh.grad = torch.from_numpy(np.sum(grad_dVhh, 0))#dVhh.sum(0)
        self.ch.grad = torch.from_numpy(np.sum(grad_dch, 0))#dch.sum(0)
        # self.Vhh.grad = dVhh.sum(0)
        # self.ch.grad = dch.sum(0)
        #breakpoint()


    def _calc_f_grads(self, x, h, h_, cost, out, target):
        # h_ -> target
        dWhh = torch.zeros((self.seq_length, self.n_hid, self.n_hid), requires_grad=False)
        dWxh = torch.zeros((self.seq_length, self.n_inp, self.n_hid), requires_grad=False)
        dbh = torch.zeros((self.seq_length, self.n_hid), requires_grad=False)
        dWhy, dby = torch.autograd.grad(cost, (self.Why, self.by), retain_graph=True)

        def forward_grads_final(hp, hp_cap, h):
            # hp_cap -> label
            # hp -> pred output
            
            pers = h.shape[1]
            hp_error = hp - hp_cap                             # predictions - truth
            # self.Why.shape = (100,4)
            # h -> (100, 20), 20 is batch_size
            grad_F = np.dot(h, hp_error)/pers
            grad_f = np.sum(hp_error, axis=0, keepdims=True)/pers
            return grad_F, grad_f

        cost_np = cost.detach().numpy()
        out_np = out.detach().numpy()
        target_np = target.detach().numpy()
        h_last_np = h[-1].detach().numpy().T
        # dloss_dwhy = np.dot(cost_np, (out_np-target_np))
        # grad_dwhy = np.dot(h_last_np, dloss_dwhy)
        # grad_dby = np.sum(dloss_dwhy, axis=0)
        grad_dwhy, grad_dby = forward_grads_final(out_np, target_np, h_last_np)
        #breakpoint()
        # dloss_dwhy = np.dot(cost, (out)-target))
        # grad_dwhy = np.dot(h[-1].T, dloss_dwhy)
        
        # dWhh[0], dWxh[0], dbh[0] = torch.autograd.grad(self._mse(h[0], h_[0]),
        #                                                (self.Whh, self.Wxh, self.bh), retain_graph=True)
        # cost_np = self._mse(h[0], h_[0]).detach().numpy()
        # out = h[0].detach().numpy()
        # target_np = h_[0].detach().numpy()
        # dloss_dwhh = np.dot(cost_np, (out-target_np))
        # grad_dwhh = np.dot(x[0].T,dloss_dwhh)
        grad_dWhh = torch.zeros((self.seq_length, self.n_hid, self.n_hid), requires_grad=False).detach().numpy()
        grad_dWxh = torch.zeros((self.seq_length, self.n_inp, self.n_hid), requires_grad=False).detach().numpy()
        grad_dbh = torch.zeros((self.seq_length, self.n_hid), requires_grad=False).detach().numpy()
        def forward_grads(hp, hp_cap, h):
            def relu_derivative(x):
                # return (x>0)*1-(x<=0)*0.01
                return (x>0)*1
                pass
            def tanh_derivative(x):
                return 1 - np.tanh(x)**2
            pers = h.shape[1]
            hp_error = hp - hp_cap
            grad_F = np.dot((2 * hp_error * tanh_derivative(hp)).T, h).T/pers
            grad_f = np.sum(2 * hp_error * tanh_derivative(hp), axis=0, keepdims=True)/pers

            return grad_F, grad_f
        for t in range(0, len(h)):
            dWhh[t], dWxh[t], dbh[t] = torch.autograd.grad(self._mse(h[t], h_[t].detach()),
                                                           (self.Whh, self.Wxh, self.bh), retain_graph=True)
            # ht = self.Whh*xt + self.bh
            # xt = Wxh*(ht-1)
            # h -> output
            # h_ -> pred
            grad_dWhh[t], grad_dbh[t] = forward_grads(h[t].detach().numpy(), h_[t].detach().numpy(), h[t-1].detach().numpy())
            grad_dbh[t] = grad_dbh[t].flatten()
            grad_dWxh[t], _ = forward_grads(h[t].detach().numpy(), h_[t].detach().numpy(), x[t-1].detach().numpy())
            # cost_np = self._mse(h[t], h_[t]).detach().numpy()
            # out = h[t].detach().numpy()
            # target_np = h_[t].detach().numpy()
            # out_prev = h[t-1].detach().numpy()
            # dloss_dwhh = np.dot(cost_np, (out-target_np))
            # grad_dwhh = np.dot(out_prev.T,dloss_dwhh)

            # cost_np = self._mse(h[t], h_[t]).detach().numpy()
            # out = h[t].detach().numpy()
            # target_np = h_[t].detach().numpy()
            # dloss_dwxh = np.dot(cost_np, (out-target_np))
            # grad_dwhh = np.dot(x[t].T,dloss_dwhh)
        #breakpoint()
            # self.Whh.grad[-1] 2.2629e-08,  2.3674e-08,  2.8578e-09,  0.0000e+00, -1.8849e-08]
            # whh[-1] 0.0549, -0.0004,  0.0714,  0.0505], grad_fn=<SelectBackward0>)
        
        self.Whh.grad = torch.from_numpy(np.sum(grad_dWhh, axis=0))#dWhh.sum(0)
        self.Wxh.grad = torch.from_numpy(np.sum(grad_dWxh, axis=0))#dWxh.sum(0)
        self.bh.grad = torch.from_numpy(np.sum(grad_dbh, axis=0))#dbh.sum(0)
        grad_dwhy = grad_dwhy.astype(np.float32)
        self.Why.grad = torch.from_numpy(grad_dwhy)#dWhy
        grad_dby = grad_dby.astype(np.float32)
        self.by.grad = torch.from_numpy(grad_dby.flatten())#dby.clone()

        # self.Whh.grad = dWhh.sum(0)
        # self.Wxh.grad = dWxh.sum(0)
        # self.bh.grad = dbh.sum(0)
        # self.Why.grad = dWhy
        # self.by.grad = dby.clone()
        #breakpoint()


    def forward(self, x, y):
        h = self._hidden(x)
        # new work implementation:
        #hs_tmax = self._sample(h[-1]).clone().detach().requires_grad_(True)
        # the above is what the code used for this work, not the OG DTP work we are replicating
        #hs_tmax = h[-1].clone().detach().requires_grad_(True) # in the context of the OG DTP work, hst_max = ht
        hs_tmax = h[-1].clone().detach().requires_grad_(True)
        out = hs_tmax @ self.Why + self.by
        if self.last_layer == "softmax":
            out = self.sftmx(out)
        elif self.last_layer == "linear":
            pass
        else:
            raise Exception("Unsupported classification type.")

        return hs_tmax, h, out
        

    def _validate(self, x):
        n_val_samples = x.shape[1]
        h0 = torch.zeros(n_val_samples, self.n_hid)
        h = torch.empty(self.seq_length, n_val_samples, self.n_hid)
        h[0, :, :] = self._f(x[0, :, :], h0)
        for t in range(1, self.seq_length):
            h[t, :, :] = self._f(x[t, :, :], h[t - 1].clone())

        out = h[-1] @ self.Why + self.by

        if self.last_layer == "softmax":
            out = self.sftmx(out)
        elif self.last_layer != "linear":
            raise Exception("Unsupported classification type.")

        return out


    def run_validation(self, x, y, avg_probs_100=True):

        valid_cost = 0
        valid_err = 0

        # Stochastic validation
        if self.stochastic & avg_probs_100:
            out = torch.stack([self._validate(x) for i in range(100)]).mean(axis=0)
        else:
            out = self._validate(x)
        if self.last_layer == "softmax":
            valid_cost += self._cross_entropy(out, y)
            y = torch.argmax(y, 1)
            y_hat = torch.argmax(out.data, 1)
            valid_err = (~torch.eq(y_hat, y)).float().mean()
        elif self.last_layer == "linear":
            valid_cost = self._mse(out, y).sum()
            valid_err = (((y - out) ** 2).sum(axis=1) > 0.04).float().mean()
        else:
            raise Exception("Unsupported classification type.")
        if type(valid_err) == torch.Tensor:
            valid_err = valid_err.item()
        return valid_cost, valid_err


    def _step_g(self, x, y, g_optimizer):
        g_optimizer.zero_grad()

        h = self._hidden(x)

        # Corrupt targets with noise
        if self.noise != 0:
            h = self._hidden(x)
            h = h.detach() + self._gaussian(h)

        self._calc_g_grads(x, h)

        g_optimizer.step()


    def _step_f(self, ilr, x, y, f_optimizer):
        f_optimizer.zero_grad()

        out = torch.zeros(self.batch_size, self.n_out)
        for i in range(self.M):
            hs_tmax, h, out_ = self.forward(x, y)
            out = out + out_
        out = out / self.M

        if self.last_layer == "softmax":
            cost = self._cross_entropy(out, y)
        elif self.last_layer == "linear":
            cost = self._mse(out, y).sum()
        else:
            raise Exception("Unsupported classification type.")

        error = out - y
        with torch.no_grad():
            h_ = self._get_targets(x, hs_tmax, h, cost, ilr, error)

        self._calc_f_grads(x, h, h_, cost, out, y)
        
        #pre_dwhh = self.Whh
        f_optimizer.step()
        return cost


    def fit(self, ilr, maxiter, g_optimizer, f_optimizer, task, rng, check_interval=1):

        training = True
        epoch = 1
        best = 0

        n_batches = self.X.shape[1] // self.batch_size
        accs = []
        while training & (epoch <= maxiter):
            
            if epoch == 1:
                with torch.no_grad():
                    _, best = self.run_validation(self.X_test, self.y_test)
                acc = 100 * (1 - best)
                print("Epoch -- \t Cost -- \t Test Acc: %.2f \t Highest: %.2f" % (acc, acc))

            cost = 0
            # Inverse mappings
            for i in range(n_batches):
                batch_start_idx = i * self.batch_size
                batch_end_idx = batch_start_idx + self.batch_size
                x = self.X[:, batch_start_idx:batch_end_idx, :]
                y = self.y[batch_start_idx:batch_end_idx, :]
                self._step_g(x, y, g_optimizer)

            # Forward mappings
            for i in range(n_batches):
                batch_start_idx = i * self.batch_size
                batch_end_idx = batch_start_idx + self.batch_size
                x = self.X[:, batch_start_idx:batch_end_idx, :]
                y = self.y[batch_start_idx:batch_end_idx, :]

                cost += self._step_f(ilr, x, y, f_optimizer)
                if torch.isnan(cost):
                    print("Cost is NaN. Aborting....")
                    training = False
                    break

            cost = cost / n_batches
            if epoch % check_interval == 0:
                with torch.no_grad():
                    valid_cost, valid_err = self.run_validation(self.X_test, self.y_test)

                print_str = "It: {:10s}\tLoss: %.3f\t".format(str(epoch)) % cost

                whh_grad_np = self.Whh.detach().numpy()
                vhh_grad_np = self.Vhh.detach().numpy()
                if np.isnan(whh_grad_np).any():
                    print_str += "ρ|Whh|: -----\t"
                else:
                    print_str += "ρ|Whh|: %.3f\t" % np.max(abs(np.linalg.eigvals(whh_grad_np)))

                if np.isnan(vhh_grad_np).any():
                    print_str += "ρ|Vhh|: -----\t"
                else:
                    print_str += "ρ|Vhh|: %.3f\t" % np.max(abs(np.linalg.eigvals(vhh_grad_np)))

                dWhh = np.linalg.norm(self.Whh.grad.numpy())
                dWxh = np.linalg.norm(self.Wxh.grad.numpy())
                dWhy = np.linalg.norm(self.Why.grad.numpy())

                acc = 100 * (1 - valid_err)

                if acc > best:
                    best = acc

                print_str += "dWhh: %.5f\t dWxh: %.5f\t dWhy: %.5f\t" % (dWhh, dWxh, dWhy)
                print_str += "Acc: %.2f\tVal.loss: %.2f\tHighest: %.2f\t" % (acc, valid_cost, best)
                print_str += "ρ|val_err|: %.3f\t" % (valid_err*100)
                accs.append(acc)
                print(print_str)

                if valid_err < 0.0001:
                    print("PROBLEM SOLVED.")
                    training = False
            #print(f"Epoch: {epoch}")
            epoch += 1
        #breakpoint()
        import pickle
        from datetime import datetime
        date = datetime.now()
        with open(f'accuracy_data_{date}_no_auto_grad.pkl', 'wb') as f:
            pickle.dump(accs, f)
        return best, cost.item()

def sample_length(min_length, max_length, rng):
    """
    Computes a sequence length based on the minimal and maximal sequence size.

    Parameters
    ----------
    max_length      : maximal sequence length (t_max)
    min_length      : minimal sequence length

    Returns
    -------
    A random number from the max/min interval
    """
    length = min_length

    if max_length > min_length:
        length = min_length + rng.randint(max_length - min_length)

    return length

def run_experiment(seed, init, task_name, opt, seq, hidden, stochastic, hybrid, batch, maxiter, i_learning_rate,
                   f_learning_rate, g_learning_rate, noise, M, check_interval=10):
    
    torch.manual_seed(seed)
    model_rng = np.random.RandomState(seed)
    rng = model_rng
    # task = TempOrderTask(rng, "float32")
    # val_batch = 1000
    # X, y = task.generate(batch, sample_length(seq, seq, rng))
    # X_test, y_test = task.generate(val_batch, sample_length(seq, seq, rng))
    last_layer = "softmax"
    task = "MNIST"
    sample_train = 10000
    sample_test  = 1000
    X, y, X_test, y_test = load_MNIST("mnist_8x8", one_hot=True, 
                                        norm=False, sample_train=sample_train, 
                                        sample_test=sample_test)

    #breakpoint()
    
    # if task_name == "task_A":
    #     n_samples = 3000
    #     n_test = 100
    #     last_layer = "softmax"
    #     X, y, X_test, y_test = get_classA(seq, n_samples, n_test)  # X [n_batches, batch_size, n_inp]
    # else:
    #     print("Unknown task %s. Aborting..." % task_name)
    #     return

    model = SRNN(X, y, X_test, y_test, seq, hidden, init, stochastic, hybrid, last_layer, noise, batch, M, model_rng)

    model_g_parameters = [model.Vhh, model.ch]

    model_f_parameters = [model.Whh, model.bh, model.Wxh, model.Why, model.by]

    if opt == "SGD":
        g_optimizer = optim.SGD(model_g_parameters, lr=g_learning_rate, momentum=0.0, nesterov=False)
        f_optimizer = optim.SGD(model_f_parameters, lr=f_learning_rate, momentum=0.0, nesterov=False)
    elif opt == "Nesterov":
        g_optimizer = optim.SGD(model_g_parameters, lr=g_learning_rate, momentum=0.9, nesterov=True)
        f_optimizer = optim.SGD(model_f_parameters, lr=f_learning_rate, momentum=0.9, nesterov=True)
    elif opt == "RMS":
        g_optimizer = optim.RMSprop(model_g_parameters, lr=g_learning_rate)
        f_optimizer = optim.RMSprop(model_f_parameters, lr=f_learning_rate)
    elif opt == "Adam":
        g_optimizer = optim.Adam(model_g_parameters, lr=g_learning_rate)
        f_optimizer = optim.Adam(model_f_parameters, lr=f_learning_rate)
    elif opt == "Adagrad":
        g_optimizer = torch.optim.Adagrad(model_g_parameters, lr=g_learning_rate)
        f_optimizer = torch.optim.Adagrad(model_f_parameters, lr=f_learning_rate)
    else:
        print("Unknown optimiser %s. Aborting..." % opt)
        return


    print("SRNN TPTT Network")
    print("--------------------")
    print("stochastic : %s" % stochastic)
    if stochastic:
        print("MCMC       : %i" % M)
        print("Hybrid     : %s" % hybrid)
    print("task name  : %s" % task_name)
    print("train size : %i" % (X.shape[1]))
    print("test size  : %i" % (X_test.shape[1]))
    print("batch size : %i" % batch)
    print("T          : %i" % seq)
    print("n_hid      : %i" % hidden)
    print("init       : %s" % init.__name__)
    print("maxiter    : %i" % maxiter)
    print("chk        : %i" % check_interval)
    print("--------------------")
    print("optimiser : %s" % opt)
    print("ilr       : %.5f" % i_learning_rate)
    print("flr       : %.5f" % f_learning_rate)
    print("glr       : %.5f" % g_learning_rate)
    if noise != 0:
        print("noise     : %.5f" % noise)
    else:
        print("noise     : ---")
    print("--------------------")

    val_acc, tr_cost = model.fit(i_learning_rate, maxiter, g_optimizer, f_optimizer, task, rng, check_interval)
    file_name = "rnn_stptt_" + "t" + str(seq) + "_taskA_i" \
                + str(i_learning_rate) + "_f" + str(f_learning_rate) + "_g" \
                + str(g_learning_rate) + "_" + init.__name__  + opt.lower()

    #model.plot_classA(file_name + ".png")

    return val_acc, tr_cost
    


def load_MNIST(data_folder, one_hot = False, norm = True, sample_train = 0, sample_test = 0):
    """
    Loads, samples (if needed), and one-hot encodes the MNIST data set.
            
    Parameters
    ----------
    data_folder   : location of the MNIST data
    one_hot       : if True the target labels will be one-hot encoded
    norm          : if True the images will be normalised
    sample_train  : fraction of the train data to use. if set to 0 no sampling
                    will be applied (i.e. 100% of the data is used)
    sample_train  : fraction of the test data to use. if set to 0 no sampling
                    will be applied (i.e. 100% of the data is used)
    Returns
    -------
    X_train - Training images. Dimensions are (784, number of samples, 1)
    y_train - Training labels. Dimensions are (number of samples, 10)
    X_test  - Test images. Dimensions are (784, number of samples, 1)
    y_test  - Test labels. Dimensions are (number of samples, 10)
    """
    X_train = np.genfromtxt("%s/train_X.csv" % data_folder, delimiter=',', dtype=np.float32)
    y_train = np.asarray(np.fromfile("%s/train_Y.csv" % data_folder, sep='\n'), dtype="int32")

    X_test = np.genfromtxt("%s/test_X.csv" % data_folder, delimiter=',', dtype=np.float32)
    y_test = np.asarray(np.fromfile("%s/test_Y.csv" % data_folder, sep='\n'), dtype="int32")   

    if (sample_train != 0) and (sample_test != 0):
        
        print("Elements in train : %i" % sample_train)
        print("Elements in test  : %i" % sample_test)
        
        idx_train = np.random.choice(np.arange(len(X_train)), sample_train, replace=False)
        idx_test = np.random.choice(np.arange(len(X_test)), sample_test, replace=False)
        
        X_train = X_train[idx_train]
        y_train = y_train[idx_train]

        X_test = X_test[idx_test]
        y_test = y_test[idx_test]

        
    if norm:
        print("MNIST NORMALISED!")
        X_train /= 255.0
        X_test  /= 255.0

    # Swap axes
    X_train = np.swapaxes(np.expand_dims(X_train,axis=0),0,2)
    X_test = np.swapaxes(np.expand_dims(X_test,axis=0),0,2)
    
    # Encode the target labels
    #breakpoint()
    if one_hot:
        onehot_encoder = OneHotEncoder(sparse_output=False, categories="auto")        
        y_train = onehot_encoder.fit_transform(y_train.reshape(-1,1))
        y_test = onehot_encoder.fit_transform(y_test.reshape(-1,1))
    return X_train, y_train, X_test, y_test


def main():
    batch = 16
    hidden = 100
    maxiter = 2
    i_learning_rate = 0.0000001
    f_learning_rate = 0.01
    g_learning_rate = 0.00000001
    noise = 0.0
    M = 1

    seed = 1234

    init = nn.init.orthogonal_

    sto = False
    hybrid = True # set to false for no stochasticity

    # Experiment 1 - shallow depth
    seq = 64
    rng = np.random.RandomState(1234)

    run_experiment(seed, init, "task_A", "SGD", seq, hidden, sto, hybrid, batch, maxiter,
                  i_learning_rate, f_learning_rate, g_learning_rate, noise, M, check_interval=1)

    # # Experiment 2 - deeper network
    # seq = 30

    # run_experiment(seed, init, "task_A", "Adagrad", seq, hidden, sto, hybrid, batch, maxiter,
    #                i_learning_rate, f_learning_rate, g_learning_rate, noise, M, check_interval=100)

if __name__ == '__main__':
    main()