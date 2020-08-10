import sys,os
import random
import numpy as np
import sklearn.datasets

from scipy.stats import norm

import torch
import torch.autograd as autograd
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
from sklearn.multioutput import MultiOutputRegressor
import copy
from scipy.stats import laplace

from CCIT import *
from sklearn.linear_model import LogisticRegressionCV
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import scale
from classifier import *

torch.manual_seed(11)


use_cuda = True
CRITIC_ITERS = 5

from utilities import *


class CI_base(object):
    '''
    Base Class for CI Testing. All the parameters may not be used for GAN/Regression testing
    X,Y,Z: Arrays for input random variables
    max_depths: max_depth parameter choices for xgboost e.g [6,10,13]
    n_estimators: n_estimator parameter choices for xgboost e.g [100,200,300]
    colsample_bytrees: colsample_bytree parameter choices for xgboost e.g [100,200,300]
    nfold: cross validation number of folds
    train_samp: percentage of samples to be used for training e.g -1 for default (recommended)
    nthread: number of parallel threads for xgboost, recommended as number of processors in the machine
    max_epoch: number of epochs when mimi function is GAN
    bsize: batch size when mimic function is GAN
    dim_N: dimension of noise when GAN, if None then set to dim_z + 1, can be set to a moderate value like 20
    noise: Type of noise for regression mimic function 'Laplace' or 'Normal' or 'Mixture'
    perc: percentage of mixture Normal for noise type 'Mixture'
    normalized: Normalize data-set or not
    '''
    def __init__(self,X,Y,Z,max_depths = [6,10,13], n_estimators=[100,200,300], colsample_bytrees=[0.8],nfold = 5,\
        train_samp = -1,nthread = 4,max_epoch=100,bsize=50,dim_N = None, noise = 'Laplace',perc = 0.3, normalized = True,\
        deep_classifier = False,params =  {'nhid':20,'nlayers':3}):
        self.X = X
        self.Y = Y
        self.Z = Z
        self.max_depths = max_depths
        self.n_estimators = n_estimators
        self.colsample_bytrees = colsample_bytrees
        self.nfold = nfold
        self.train_samp = train_samp
        self.nthread = nthread
        self.max_epoch = max_epoch
        self.bsize = bsize
        self.dim_N = dim_N
        self.noise = noise
        self.perc = perc
        self.normalized = normalized
        self.dc = deep_classifier
        self.params = params
        np.random.seed(11)
        
        assert (type(X) == np.ndarray),"Not an array"
        assert (type(Y) == np.ndarray),"Not an array"
        assert (type(Z) == np.ndarray),"Not an array"
    
        self.nx,self.dx = X.shape
        self.ny,self.dy = Y.shape
        self.nz,self.dz = Z.shape 

        assert (self.nx == self.ny), "Size Mismatch"
        assert (self.nz == self.ny), "Size Mismatch"
        assert (self.nx == self.nz), "Size Mismatch"

        if self.normalized:
            X = scale(X,axis=0,with_mean = False)
            Y = scale(Y,axis=0,with_mean = False)
            Z = scale(Z,axis=0,with_mean = False)

    def CI_classify(self):
        np.random.seed(11)
        if self.train_samp == -1:
            self.num_train = int(2.0*self.nx/3.0)
            Xtrain,Ytrain,Xtest,Ytest = self.mimic_sampler(self.X,self.Y,self.Z, self.param_dict)
        else:
            self.num_train = 2*self.train_samp*self.nx
            self.param_dict['train_len'] = 2*self.train_samp*self.nx
            Xtrain,Ytrain,Xtest,Ytest = self.mimic_sampler(self.X,self.Y,self.Z, self.param_dict)

        if self.dc:
            params = self.params
            model = MLP(params,Xtrain.shape[1],2,cudaEfficient=True)
            model.fit(Xtrain,Ytrain.astype(int),validation_split=0.2)
            gbm = model
            pred = gbm.predict_proba(torch.from_numpy(Xtest).float())
            pred_exact = np.argmax(pred,axis =1)
            acc1 = sklearn.metrics.accuracy_score(Ytest, pred_exact)
            AUC1 = sklearn.metrics.roc_auc_score(Ytest,pred[:,1])
            del gbm
            model = MLP(params,Xtrain[:,self.dx::].shape[1],2,cudaEfficient=True)
            model.fit(Xtrain[:,self.dx::],Ytrain.astype(int),validation_split=0.2)
            gbm = model
            pred = gbm.predict_proba(torch.from_numpy(Xtest[:,self.dx::]).float())
            pred_exact = np.argmax(pred,axis =1)
            acc2 = sklearn.metrics.accuracy_score(Ytest, pred_exact)
            AUC2 = sklearn.metrics.roc_auc_score(Ytest,pred[:,1])
            print 'Using Deep Model: ',
            print gbm
            del gbm
        else:
            model,features,bp = XGB_crossvalidated_model(max_depths=self.max_depths, n_estimators=self.n_estimators, \
                colsample_bytrees=self.colsample_bytrees,Xtrain=Xtrain,Ytrain=Ytrain,\
                                                         nfold=self.nfold,feature_selection = 0,nthread = self.nthread)
            gbm = model.fit(Xtrain,Ytrain)
            pred = gbm.predict_proba(Xtest)
            pred_exact = np.argmax(pred,axis =1)
            acc1 = accuracy_score(Ytest, pred_exact)
            AUC1 = roc_auc_score(Ytest,pred[:,1])
            del gbm
            gbm = model.fit(Xtrain[:,self.dx::],Ytrain)
            pred = gbm.predict_proba(Xtest[:,self.dx::])
            pred_exact = np.argmax(pred,axis =1)
            acc2 = sklearn.metrics.accuracy_score(Ytest, pred_exact)
            AUC2 = sklearn.metrics.roc_auc_score(Ytest,pred[:,1])
            print 'Using XGB model: '
            print gbm
            del gbm
        
        x = [0.0, AUC1 - AUC2 , AUC2 - 0.5, acc1 - acc2, acc2 - 0.5]
        print 'AC_w_x: ' + str(AUC1),
        print 'AC_no_x: ' + str(AUC2)
        y = max(x[1],x[3])
        sigma = 1.0/np.sqrt(self.nx)
        return pvalue(x[1],sigma)
