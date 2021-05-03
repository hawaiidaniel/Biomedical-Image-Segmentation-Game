from keras.models import Model
from keras.layers import Input, Reshape, Dropout, Activation, Permute, Concatenate, GaussianNoise
from keras.optimizers import Adam
from keras import backend as K

import numpy as np
import tensorflow as tf
from nets.nets_utils import conv, ConvND, UpSamplingND, MaxPoolingND
from utils.kerasutils import get_channel_axis
from keras import objectives

from nets.custom_losses import exp_categorical_crossentropy

"""Building U-Net."""

__author__ = 'Ken C. L. Wong'


def MDL(input_tensor, nclass=2, ncluster=[], unsupervised_weight=0):
    def inner(y_true, y_pred):
        sz=tf.shape(y_true)
        flags=tf.reduce_max(tf.reduce_max(tf.reduce_max(y_true[:,:,:,1::1],-1),-1),-1)

        unseg_ind = K.tf.where(K.tf.equal(flags, 0.0))
        unseg_wh = K.tf.reshape(unseg_ind, [-1])
        ind = K.tf.where(K.tf.equal(flags, 1.0))
        wh = K.tf.reshape(ind, [-1])

        un_im  = tf.cast(tf.reshape(K.tf.gather(input_tensor, unseg_wh), [-1]), tf.int32)
        un_seg = K.tf.gather(y_pred, unseg_wh)
        bins=256
        un_entropy=0
        imsize=tf.cast(sz[1]*sz[2],tf.float32)
        for l in range(np.sum(ncluster).astype(np.int32)):
            prob=tf.reshape(un_seg[:,:,:,l],[-1])
            hist=tf.unsorted_segment_sum(prob, un_im, bins)
            sumh=tf.reduce_sum(hist)
            logp=-tf.log(tf.divide(hist+1E-10,sumh+1E-10))
            un_entropy=un_entropy+tf.reduce_sum(tf.multiply(hist,logp))/imsize

        seg_true = K.tf.gather(y_true, wh)
        seg_pred = K.tf.gather(y_pred, wh)
        ind=nclass
        entropy=0.0
        for i in range(nclass):
            yp=seg_pred[:, :, :, i]
            for j in range(ncluster[i]-1):
                yp=tf.add(yp,y_pred[:,:,:,ind])
                ind=ind+1
            entropy=tf.add(entropy, objectives.binary_crossentropy(K.batch_flatten(seg_true[:,:,:,i]), K.batch_flatten(yp)))
            # yp = K.clip(yp, K.epsilon(), 1 - K.epsilon())  # As log is used
            # entropy=tf.add(entropy, y_true[:,:,:,i] * -K.log(yp))

        if K.ndim(entropy) == 2:
            entropy = K.mean(entropy, axis=-1)

        return entropy + un_entropy * unsupervised_weight

    return inner

def CE(nclass=2, ncluster=[]):
    def inner(y_true, y_pred):
        seg_true = y_true
        seg_pred = y_pred
        ind=nclass
        entropy=0.0
        for i in range(nclass):
            yp=seg_pred[:, :, :, i]
            for j in range(ncluster[i]-1):
                yp=tf.add(yp,y_pred[:,:,:,ind])
                ind=ind+1
            entropy=tf.add(entropy, objectives.binary_crossentropy(K.batch_flatten(seg_true[:,:,:,i]), K.batch_flatten(yp)))
            # yp = K.clip(yp, K.epsilon(), 1 - K.epsilon())  # As log is used
            # entropy=tf.add(entropy, y_true[:,:,:,i] * -K.log(yp))

        if K.ndim(entropy) == 2:
            entropy = K.mean(entropy, axis=-1)

        return entropy

    return inner

# def EncodingLength_2D(input_tensor, image_weight=1.0, L=1):
#     """
#     :param exp: exponent. 1.0 for no exponential effect.
#     """
#     def inner(y_true, y_pred):
#         sz = K.shape(y_pred)
#         mv=tf.reduce_max(y_true)
#         I_weight = tf.cond(tf.equal(mv,0), lambda: tf.add(0.5,0.5), lambda: tf.add(0.0,0.0))
#         I_weight=I_weight*image_weight
#         if (I_weight==0):
#             return 0.0
#
#         bins=256
#         # sz = K.shape(y_pred)
#         entropy_sum=0
#         # entropy_seg=0
#         # im = tf.cast(tf.reshape(y_true[:, :, :, 0], [-1]),tf.int32)
#         im=input_tensor
#         # im=tf.multiply((im-tf.reduce_min(im))/(tf.reduce_max(im)-tf.reduce_min(im)),255)
#         im = tf.cast(tf.reshape(im,[-1]),tf.int32)
#         # seg_hist=tf.zeros(L,1)
#         imsize=tf.reduce_sum(y_pred)
#
#         for l in range(L):
#             prob=tf.reshape(y_pred[:,:,:,l],[-1])
#             hist = tf.unsorted_segment_sum(prob, im, bins)
#             logp=-tf.log(tf.divide(hist+1E-10,tf.reduce_sum(hist)+1E-5))
#             entropy_sum=entropy_sum+tf.reduce_sum(tf.multiply(hist,logp))/imsize
#
#         return entropy_sum * I_weight
#     return inner

def EncodingLength_2D(image_weight=1.0, L=1):
    """
    :param exp: exponent. 1.0 for no exponential effect.
    """
    def inner(y_true, y_pred):
        sz = K.shape(y_pred)
        mv=tf.reduce_max(y_true)
        I_weight = tf.cond(tf.greater(mv,50), lambda: tf.add(0.5,0.5), lambda: tf.add(0.0,0.0))
        S_weight = 1.0 - I_weight
        I_weight=I_weight*image_weight

        bins=256
        # sz = K.shape(y_pred)
        entropy_sum=0
        # entropy_seg=0
        im = tf.cast(tf.reshape(y_true[:, :, :, 0], [-1]),tf.int32)
        # seg_hist=tf.zeros(L,1)
        imsize=tf.reduce_sum(y_pred)

        for l in range(L):
            prob=tf.reshape(y_pred[:,:,:,l],[-1])
            # segsize=tf.reduce_sum(prob)+1E-10
            # entropy_seg =entropy_seg-segsize/imsize*tf.log(segsize/imsize)
            # meanprob=tf.reduce_mean(prob)
            # sumprob=tf.reduce_sum(prob)
            hist = tf.unsorted_segment_sum(prob, im, bins)
            logp=-tf.log(tf.divide(hist+1E-10,tf.reduce_sum(hist)))
            entropy_sum=entropy_sum+tf.reduce_sum(tf.multiply(hist,logp))/imsize
        # seg_prob=tf.divide(seg_hist+1E-10,tf.reduce_sum(seg_hist))
        # entropy_seg = tf.reduce_sum(tf.multiply(seg_hist,-tf.log(seg_prob)))/tf.reduce_sum(seg_hist)

        return entropy_sum * I_weight
    return inner

def exp_categorical_crossentropy_Im_mc(exp=1.0, class_weights=[],nclass=2,ncluster=[]):
    """
    :param exp: exponent. 1.0 for no exponential effect.
    """
    def inner(y_true, y_pred):
        mv=tf.reduce_max(y_true)
        I_weight = tf.cond(tf.greater(mv,50), lambda: tf.add(1.0,0.0), lambda: tf.add(0.0,0.0))
        S_weight = 1.0 - I_weight
        ind=nclass
        entropy=0.0
        for i in range(nclass):
            yp=y_pred[:, :, :, i]
            for j in range(ncluster[i]-1):
                # w=np.zeros(L)
                # w[ind]=1
                yp=tf.add(yp,y_pred[:,:,:,ind])
                ind=ind+1
            yp = K.clip(yp, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy=tf.add(entropy,y_true[:,:,:,i] * K.pow(-K.log(yp), exp) * class_weights[i])

        if K.ndim(entropy) == 2:
            entropy = K.mean(entropy, axis=-1)
        return entropy * S_weight

    return inner


# def exp_categorical_crossentropy_Im(exp=1.0, class_weights=[]):
#     """
#     :param exp: exponent. 1.0 for no exponential effect.
#     """
#
#     def inner(y_true, y_pred):
#         mv=tf.reduce_max(y_true)
#         I_weight = tf.cond(tf.greater(mv,50), lambda: tf.add(0.5,0.5), lambda: tf.add(0.0,0.0))
#         S_weight = 1.0 - I_weight
#
#         y_pred = K.clip(y_pred, K.epsilon(), 1 - K.epsilon())  # As log is used
#         entropy = y_true * K.pow(-K.log(y_pred), exp)*class_weights
#         entropy = K.sum(entropy, axis=-1)
#         if K.ndim(entropy) == 2:
#             entropy = K.mean(entropy, axis=-1)
#         return entropy * S_weight
#
#         # if len(np.unique(y_true))>50:
#         #     return 0
#         # else:
#         #     y_pred = K.clip(y_pred, K.epsilon(), 1 - K.epsilon())  # As log is used
#         #     entropy = y_true * K.pow(-K.log(y_pred), exp)*class_weights
#         #     entropy = K.sum(entropy, axis=-1)
#         #     if K.ndim(entropy) == 2:
#         #         entropy = K.mean(entropy, axis=-1)
#         #     return entropy
#     return inner

def exp_categorical_crossentropy_Im_mc_regular(exp=1.0, class_weights=[],nclass=2,ncluster=[]):
    """
    :param exp: exponent. 1.0 for no exponential effect.
    """

    def inner(y_true, y_pred):
        # sz=y_pred.shape
        mv=tf.reduce_max(y_true)
        I_weight = tf.cond(tf.equal(mv,0), lambda: tf.add(1.0,0.0), lambda: tf.add(0.0,0.0))
        S_weight = 1.0 - I_weight
        if (S_weight==0):
            return 0.0
        ind=nclass
        entropy=0.0
        for i in range(nclass):
            yp=y_pred[:, :, :, i]
            for j in range(ncluster[i]-1):
                # w=np.zeros(L)
                # w[ind]=1
                yp=tf.add(yp,y_pred[:,:,:,ind])
                ind=ind+1
            yp = K.clip(yp, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy=tf.add(entropy,y_true[:,:,:,i] * K.pow(-K.log(yp), exp) * class_weights[i])

        if K.ndim(entropy) == 2:
            entropy = K.mean(entropy, axis=-1)
        return entropy * S_weight

    return inner

def exp_categorical_crossentropy_Im_mc_regular_4label(exp=1.0, class_weights=[],nclass=2,ncluster=[]):
    """
    :param exp: exponent. 1.0 for no exponential effect.
    """
    inds=np.zeros(nclass,np.int32)
    ind=nclass
    for i in range(nclass):
        inds[i]=ind
        for j in range(ncluster[i]-1):
            ind+=1

    def inner(y_true, y_pred):
        # mv=tf.reduce_max(y_true)
        # I_weight = tf.cond(tf.equal(mv,0), lambda: tf.add(1.0,0.0), lambda: tf.add(0.0,0.0))
        # S_weight = 1.0 - I_weight
        # if (S_weight==0.0):
        #     return 0.0
        flag=y_true[0,0,0,0]
        weight_L3 = tf.cond(tf.equal(flag,3), lambda: tf.add(1.0,0.0), lambda: tf.add(0.0,0.0))

        entropy=0.0
        for i in [0,2,3]:
            yp=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp=tf.add(yp,y_pred[:,:,:,ind])
                ind=ind+1
            yp = K.clip(yp, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy=tf.add(entropy,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp), exp)))

        entropy1=0.0
        for i in [1]:
            yp1=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp1=tf.add(yp1,y_pred[:,:,:,ind])
                ind=ind+1
            yp1 = K.clip(yp1, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy1=tf.add(entropy1,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp1), exp)))

        entropy4=0.0
        for i in [4]:
            yp4=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp4=tf.add(yp4,y_pred[:,:,:,ind])
                ind=ind+1
            yp4 = K.clip(yp4, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy4=tf.add(entropy4,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp4), exp)))

        yp1_4=tf.add(yp1,yp4)
        entropy1_4=tf.add(entropy,tf.reduce_mean(y_true[:,:,:,1] * K.pow(-K.log(yp1_4), exp)))

        entropy = tf.add(entropy, tf.multiply(entropy1_4, weight_L3))
        entropy = tf.add(entropy, tf.multiply(tf.add(entropy1,entropy4),(1 - weight_L3)))
        return entropy

    return inner

def exp_categorical_crossentropy_Im_mc_regular_4label_V1(exp=1.0, class_weights=[],nclass=2,ncluster=[]):
    """
    :param exp: exponent. 1.0 for no exponential effect.
    """
    inds=np.zeros(nclass,np.int32)
    ind=nclass
    for i in range(nclass):
        inds[i]=ind
        for j in range(ncluster[i]-1):
            ind+=1

    def inner(y_true, y_pred):
        # mv=tf.reduce_max(y_true)
        # I_weight = tf.cond(tf.equal(mv,0), lambda: tf.add(1.0,0.0), lambda: tf.add(0.0,0.0))
        # S_weight = 1.0 - I_weight
        # if (S_weight==0.0):
        #     return 0.0
        flag=y_true[0,0,0,0]
        weight_L3 = tf.cond(tf.equal(flag,3), lambda: tf.add(1.0,0.0), lambda: tf.add(0.0,0.0))

        entropy=0.0
        for i in [0,2]:
            yp=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp=tf.add(yp,y_pred[:,:,:,ind])
                ind=ind+1
            yp = K.clip(yp, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy=tf.add(entropy,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp), exp)))

        entropy1=0.0
        for i in [1]:
            yp1=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp1=tf.add(yp1,y_pred[:,:,:,ind])
                ind=ind+1
            yp1 = K.clip(yp1, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy1=tf.add(entropy1,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp1), exp)))

        entropy3=0.0
        for i in [3]:
            yp3=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp3=tf.add(yp3,y_pred[:,:,:,ind])
                ind=ind+1
            yp3 = K.clip(yp3, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy3=tf.add(entropy3,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp3), exp)))

        entropy4=0.0
        for i in [4]:
            yp4=y_pred[:, :, :, i]
            ind=inds[i]
            for j in range(ncluster[i]-1):
                yp4=tf.add(yp4,y_pred[:,:,:,ind])
                ind=ind+1
            yp4 = K.clip(yp4, K.epsilon(), 1 - K.epsilon())  # As log is used
            entropy4=tf.add(entropy4,tf.reduce_mean(y_true[:,:,:,i] * K.pow(-K.log(yp4), exp)))

        yp1_3_4=tf.add(tf.add(yp1,yp3),yp4)
        entropy1_3_4=tf.add(entropy,tf.reduce_mean((y_true[:,:,:,1]+y_true[:,:,:,3]+y_true[:,:,:,4]) * K.pow(-K.log(yp1_3_4), exp)))

        entropy = tf.add(entropy, tf.multiply(entropy1_3_4, weight_L3))
        entropy = tf.add(entropy, tf.multiply(tf.add(tf.add(entropy1,entropy3),entropy4),(1 - weight_L3)))
        return entropy

    return inner

def VoI_Im_2D(y_true, y_pred, sigma=0.1):
    sz = K.shape(y_pred)
    imind=0
    M_true_00 = tf.abs(y_true[:, 0:sz[1] - 2, 0:sz[2]-2,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_01 = tf.abs(y_true[:, 0:sz[1] - 2, 1:sz[2]-1,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_02 = tf.abs(y_true[:, 0:sz[1] - 2, 2:sz[2],imind]   - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_10 = tf.abs(y_true[:, 1:sz[1] - 1, 0:sz[2]-2,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_11 = tf.abs(y_true[:, 1:sz[1] - 1, 1:sz[2]-1,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_12 = tf.abs(y_true[:, 1:sz[1] - 1, 2:sz[2],imind]   - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_20 = tf.abs(y_true[:, 2:sz[1]    , 0:sz[2]-2,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_21 = tf.abs(y_true[:, 2:sz[1]    , 1:sz[2]-1,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])
    M_true_22 = tf.abs(y_true[:, 2:sz[1]    , 2:sz[2]  ,imind] - y_true[:, 1:sz[1]-1, 1:sz[2]-1, imind])

    M_true_00 = tf.exp(-M_true_00 * sigma)
    M_true_01 = tf.exp(-M_true_01 * sigma)
    M_true_02 = tf.exp(-M_true_02 * sigma)
    M_true_10 = tf.exp(-M_true_10 * sigma)
    M_true_11 = tf.exp(-M_true_11 * sigma)
    M_true_12 = tf.exp(-M_true_12 * sigma)
    M_true_20 = tf.exp(-M_true_20 * sigma)
    M_true_21 = tf.exp(-M_true_21 * sigma)
    M_true_22 = tf.exp(-M_true_22 * sigma)

    M_pred_00 = tf.reduce_sum(tf.minimum(y_pred[:, 0:sz[1] - 2, 0:sz[2]-2,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_01 = tf.reduce_sum(tf.minimum(y_pred[:, 0:sz[1] - 2, 1:sz[2]-1,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_02 = tf.reduce_sum(tf.minimum(y_pred[:, 0:sz[1] - 2, 2:sz[2],:]  , y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_10 = tf.reduce_sum(tf.minimum(y_pred[:, 1:sz[1] - 1, 0:sz[2]-2,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_11 = tf.reduce_sum(tf.minimum(y_pred[:, 1:sz[1] - 1, 1:sz[2]-1,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_12 = tf.reduce_sum(tf.minimum(y_pred[:, 1:sz[1] - 1, 2:sz[2],:]  , y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_20 = tf.reduce_sum(tf.minimum(y_pred[:, 2:sz[1]    , 0:sz[2]-2,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_21 = tf.reduce_sum(tf.minimum(y_pred[:, 2:sz[1]    , 1:sz[2]-1,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
    M_pred_22 = tf.reduce_sum(tf.minimum(y_pred[:, 2:sz[1]    , 2:sz[2]  ,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)

    M_true = M_true_00 + M_true_01 + M_true_02 + M_true_10 + M_true_11 + M_true_12 + M_true_20 + M_true_21 + M_true_22
    M_pred = M_pred_00 + M_pred_01 + M_pred_02 + M_pred_10 + M_pred_11 + M_pred_12 + M_pred_20 + M_pred_21 + M_pred_22
    M_join = tf.multiply(M_pred_00, M_true_00) + tf.multiply(M_pred_01, M_true_01) + tf.multiply(M_pred_02, M_true_02) + tf.multiply(M_pred_10, M_true_10) + tf.multiply(M_pred_11, M_true_11) + tf.multiply(M_pred_12, M_true_12) + tf.multiply(M_pred_20, M_true_20) + tf.multiply(M_pred_21, M_true_21) + tf.multiply(M_pred_22, M_true_22)


    en_true = - tf.reduce_mean(tf.log(M_true))
    en_pred = - tf.reduce_mean(tf.log(M_pred))
    en_join = - tf.reduce_mean(tf.log(M_join))

    VoI = en_join * 2 - en_pred - en_true
    # return VoI / (tf.log(9.0) + en_join)
    return VoI

def Cut_Im_2D(image, unsupervised_weight=0.0):
    def inner(y_true, y_pred, sigma=0.1):
        sz = K.shape(y_pred)
        M_im_00 = tf.abs(image[:, 0:sz[1] - 2, 0:sz[2]-2] - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_01 = tf.abs(image[:, 0:sz[1] - 2, 1:sz[2]-1] - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_02 = tf.abs(image[:, 0:sz[1] - 2, 2:sz[2]]   - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_10 = tf.abs(image[:, 1:sz[1] - 1, 0:sz[2]-2] - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_11 = tf.abs(image[:, 1:sz[1] - 1, 1:sz[2]-1] - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_12 = tf.abs(image[:, 1:sz[1] - 1, 2:sz[2]]   - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_20 = tf.abs(image[:, 2:sz[1]    , 0:sz[2]-2] - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_21 = tf.abs(image[:, 2:sz[1]    , 1:sz[2]-1] - image[:, 1:sz[1]-1, 1:sz[2]-1])
        M_im_22 = tf.abs(image[:, 2:sz[1]    , 2:sz[2]  ] - image[:, 1:sz[1]-1, 1:sz[2]-1])

        M_pred_00 = tf.reduce_sum(tf.minimum(y_pred[:, 0:sz[1] - 2, 0:sz[2]-2,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_01 = tf.reduce_sum(tf.minimum(y_pred[:, 0:sz[1] - 2, 1:sz[2]-1,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_02 = tf.reduce_sum(tf.minimum(y_pred[:, 0:sz[1] - 2, 2:sz[2],:]  , y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_10 = tf.reduce_sum(tf.minimum(y_pred[:, 1:sz[1] - 1, 0:sz[2]-2,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_11 = tf.reduce_sum(tf.minimum(y_pred[:, 1:sz[1] - 1, 1:sz[2]-1,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_12 = tf.reduce_sum(tf.minimum(y_pred[:, 1:sz[1] - 1, 2:sz[2],:]  , y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_20 = tf.reduce_sum(tf.minimum(y_pred[:, 2:sz[1]    , 0:sz[2]-2,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_21 = tf.reduce_sum(tf.minimum(y_pred[:, 2:sz[1]    , 1:sz[2]-1,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)
        M_pred_22 = tf.reduce_sum(tf.minimum(y_pred[:, 2:sz[1]    , 2:sz[2]  ,:], y_pred[:, 1:sz[1]-1, 1:sz[2]-1, :]), axis=-1)

        # in_cost = tf.reduce_mean(tf.multiply(M_im_00, M_pred_00) + tf.multiply(M_im_01, M_pred_01) + tf.multiply(M_im_02,M_pred_02) + tf.multiply(M_im_10, M_pred_10) + tf.multiply(M_im_11, M_pred_11) + tf.multiply(M_im_12,M_pred_12)+ tf.multiply(M_im_20, M_pred_20) + tf.multiply(M_im_11, M_pred_21) + tf.multiply(M_im_12, M_pred_22))
        in_cost = tf.multiply(M_im_00, M_pred_00)
        in_cost = tf.add(in_cost, tf.multiply(M_im_01, M_pred_01))
        in_cost = tf.add(in_cost, tf.multiply(M_im_02, M_pred_02))
        in_cost = tf.add(in_cost, tf.multiply(M_im_10, M_pred_10))
        in_cost = tf.add(in_cost, tf.multiply(M_im_11, M_pred_11))
        in_cost = tf.add(in_cost, tf.multiply(M_im_12, M_pred_12))
        in_cost = tf.add(in_cost, tf.multiply(M_im_20, M_pred_20))
        in_cost = tf.add(in_cost, tf.multiply(M_im_21, M_pred_21))
        in_cost = tf.add(in_cost, tf.multiply(M_im_22, M_pred_22))
        in_cost=tf.reduce_mean(in_cost)

        # cross_cost = tf.reduce_mean(tf.multiply(M_im_00, (1 - M_pred_00)) + tf.multiply(M_im_01, (1 - M_pred_01)) + tf.multiply(M_im_02, (1 - M_pred_02)) + tf.multiply(M_im_10, (1 - M_pred_10)) + tf.multiply(M_im_11, (1 - M_pred_11)) + tf.multiply(M_im_12, (1 - M_pred_12)) + tf.multiply(M_im_20, (1 - M_pred_20)) + tf.multiply(M_im_21, (1 - M_pred_21)) + tf.multiply(M_im_22, (1 - M_pred_22)))
        cross_cost = tf.multiply(M_im_00, (1 - M_pred_00))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_01, (1 - M_pred_01)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_02, (1 - M_pred_02)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_10, (1 - M_pred_10)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_11, (1 - M_pred_11)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_12, (1 - M_pred_12)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_20, (1 - M_pred_20)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_21, (1 - M_pred_21)))
        cross_cost = tf.add(cross_cost, tf.multiply(M_im_22, (1 - M_pred_22)))
        cross_cost=tf.reduce_mean(cross_cost)

        return (in_cost-cross_cost) * unsupervised_weight
    return inner

def combine_loss(losses, weights):
    def inner(y_true, y_pred):
        output = 0.0
        for loss, w in zip(losses, weights):
            loss = loss(y_true, y_pred)
            if K.ndim(loss) == 2:
                loss = K.mean(loss, axis=-1)
            output += w * loss
        return output
    return inner


def build_net(
        base_num_filters=16,
        convs_per_depth=2,
        kernel_size=3,
        num_classes=2,
        image_size=(256, 256),
        kernel_cc_weight=0.0,
        activation='relu',
        dropout_rate=0.0,
        optimizer=Adam(lr=1e-4),
        net_depth=4,
        conv_order='conv_first',
        noise_std=None,
        ncluster=[],
        unsupervised_weight=0.0,
        class_weights=[],
        # loss=exp_categorical_crossentropy(exp=1.0)
):
    """Builds a U-Net.
    """

    image_size = tuple(image_size)
    if any(sz / 2 ** net_depth == 0 for sz in image_size):
        raise RuntimeError('Mismatch between image size and network depth.')

    # Preset parameters of different functions
    func = UnetFunctions(base_num_filters=base_num_filters, convs_per_depth=convs_per_depth, kernel_size=kernel_size,
                         activation=activation, conv_order=conv_order)

    channels_first = K.image_data_format() == 'channels_first'

    if channels_first:
        inputs = Input((1,) + image_size)
        # finputs = Input((1,1))
    else:
        inputs = Input(image_size + (1,))
        # finputs = Input((1,1))

    x = inputs

    if noise_std is not None:
        x = GaussianNoise(noise_std)(x)

    # Contracting path
    for depth in range(net_depth):
        x = func.contract(depth,kernel_cc_weight=kernel_cc_weight)(x)

    # Deepest layer
    num_filters = base_num_filters * 2 ** net_depth
    x = Dropout(dropout_rate)(x) if dropout_rate else x
    x = func.conv_depth(num_filters=num_filters, name='encode')(x)

    # Expanding path
    for depth in reversed(range(net_depth)):
        x = func.expand(depth, kernel_cc_weight=kernel_cc_weight)(x)

    # Segmentation layer and loss function related
    x = ConvND(x, filters=np.sum(ncluster), kernel_size=1, activation=None, name='segmentation')(x)
    if channels_first:
        new_shape = tuple(range(1, K.ndim(x)))
        new_shape = new_shape[1:] + new_shape[:1]
        x = Permute(new_shape)(x)
    # x = Reshape((np.prod(image_size), num_classes))(x)
    x = Activation('softmax')(x)
    model = Model(inputs=inputs, outputs=x)
    # model.compile(optimizer=optimizer, loss=loss)
    # model.compile(optimizer=optimizer, loss=combine_loss([Cut_Im_2D(image=inputs, unsupervised_weight=unsupervised_weight),
    #               exp_categorical_crossentropy_Im_mc_regular_4label(exp=1.0, nclass=num_classes, ncluster=ncluster)], [0.5, 0.5]))
    # model.compile(optimizer=optimizer, loss=combine_loss([EncodingLength_2D(image_weight=unsupervised_weight, L=num_classes),
    #               exp_categorical_crossentropy_Im_mc(exp=1.0, nclass=num_classes, class_weights=class_weights, ncluster=ncluster)], [0.5, 0.5]))
    model.compile(optimizer=optimizer, loss=exp_categorical_crossentropy_Im_mc_regular_4label_V1(exp=1.0, nclass=num_classes, ncluster=ncluster))
    # model.compile(optimizer=optimizer, loss=EncodingLength_2D(input_tensor=inputs, image_weight=unsupervised_weight, L=num_classes))
    # model.compile(optimizer=optimizer, loss=MDL(inputs,nclass=num_classes, ncluster=ncluster, unsupervised_weight=unsupervised_weight))
    # model.compile(optimizer=optimizer, loss=CE(nclass=num_classes, ncluster=ncluster))

    return model


class UnetFunctions(object):
    """Provides U-net related functions."""

    def __init__(self, base_num_filters=16, convs_per_depth=2, kernel_size=3, activation='relu',
                 conv_order='conv_first', use_batch_norm=True, dilation_rate=1):
        self.base_num_filters = base_num_filters
        self.convs_per_depth = convs_per_depth
        self.kernel_size = kernel_size
        self.activation = activation
        self.conv_order = conv_order
        self.use_batch_norm = use_batch_norm
        self.dilation_rate = dilation_rate
        self.contr_tensors = dict()

    def local_conv(self, num_filters, dilation_rate, name=None, kernel_cc_weight=0.0):
        return conv(num_filters=num_filters, kernel_size=self.kernel_size, activation=self.activation,
                    conv_order=self.conv_order, use_batch_norm=self.use_batch_norm, name=name,
                    dilation_rate=dilation_rate, kernel_cc_weight=kernel_cc_weight)

    def conv_depth(self, num_filters, dilation_rate=None, name=None, kernel_cc_weight=0.0):
        """conv block for a depth."""

        if dilation_rate is None:
            dilation_rate = self.dilation_rate

        def composite_layer(x):
            for c in range(self.convs_per_depth):
                if c != self.convs_per_depth - 1:
                    x = self.local_conv(num_filters=num_filters, dilation_rate=dilation_rate, kernel_cc_weight= kernel_cc_weight)(x)
                else:
                    x = self.local_conv(num_filters=num_filters, dilation_rate=dilation_rate, name=name, kernel_cc_weight=kernel_cc_weight)(x)
            return x

        return composite_layer

    def contract(self, depth, kernel_cc_weight=0.0):
        """Returns a contraction layer."""

        def composite_layer(x):
            name = 'contr_%d' % depth
            num_filters = self.base_num_filters * 2 ** depth
            x = self.conv_depth(num_filters=num_filters, name=name, kernel_cc_weight=kernel_cc_weight)(x)
            self.contr_tensors[depth] = x
            x = MaxPoolingND(x)(x)
            return x

        return composite_layer

    def expand(self, depth, kernel_cc_weight=0.0):
        """Returns an expansion layer."""

        def composite_layer(x):
            """
            Arguments:
            x: tensor from the previous layer.
            """
            name = 'expand_%d' % depth
            num_filters = self.base_num_filters * 2 ** depth
            x = UpSamplingND(x)(x)
            x = Concatenate(axis=get_channel_axis(), name='concat_%d' % depth)([x, self.contr_tensors[depth]])
            x = self.conv_depth(num_filters=num_filters, name=name, kernel_cc_weight=kernel_cc_weight)(x)
            return x

        return composite_layer
