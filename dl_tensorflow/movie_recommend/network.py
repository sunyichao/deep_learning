# -*- coding: utf-8 -*-
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import time
import datetime
import pickle
import numpy as np
import tensorflow as tf
from tensorflow.python.ops import math_ops
from sklearn.model_selection import train_test_split


# 读取数据
title_count, title_set, genres2int, features, targets_values, ratings, users, movies, data, movies_orig, users_orig = pickle.load(
    open('./data/ml-1m/preprocess.p', mode='rb'))

#嵌入矩阵的维度
embed_dim = 32
#用户ID个数
uid_max = max(features.take(0,1)) + 1 # 6040
#性别个数
gender_max = max(features.take(2,1)) + 1 # 1 + 1 = 2
#年龄类别个数
age_max = max(features.take(3,1)) + 1 # 6 + 1 = 7
#职业个数
job_max = max(features.take(4,1)) + 1# 20 + 1 = 21
#电影ID个数
movie_id_max = max(features.take(1,1)) + 1 # 3952
#电影类型个数
movie_categories_max = max(genres2int.values()) + 1 # 18 + 1 = 19
#电影名单词个数
movie_title_max = len(title_set) # 5216
#对电影类型嵌入向量做加和操作的标志，考虑过使用mean做平均，但是没实现mean
combiner = "sum"
#电影名长度
sentences_size = title_count # = 15
#文本卷积滑动窗口，分别滑动2, 3, 4, 5个单词
window_sizes = {2, 3, 4, 5}
#文本卷积核数量
filter_num = 8
#电影ID转下标的字典，数据集中电影ID跟下标不一致，比如第5行的数据电影ID不一定是5
movieid2idx = {val[0]:i for i, val in enumerate(movies.values)}
num_epochs = 5
# Batch Size
batch_size = 256

dropout_keep = 0.5
learning_rate = 0.0001
# Show stats for every n number of batches
show_every_n_batches = 20

save_dir = './models/mr/save'


def save_params(params):
    pickle.dump(params, open('./models/mr/params.p', 'wb'))
    print("params saved")

def load_params():
    return pickle.load(open('./models/mr/params.p', mode='rb'))

def get_batches(Xs, ys, batch_size):
    for start in range(0, len(Xs), batch_size):
        end = min(start + batch_size, len(Xs))
        yield Xs[start:end], ys[start:end]

def get_params_inputs():
    """
    定义输入的占位符
    """
    targets = tf.placeholder(tf.int32, [None, 1], name="targets")
    learningRate = tf.placeholder(tf.float32, name="learning_rate")
    dropout_keep_prob = tf.placeholder(tf.float32, name="dropout_keep_prob")
    y_ = tf.placeholder(tf.float32, name="y_")
    
    return targets, learningRate, dropout_keep_prob

def get_usr_inputs():
    """
    定义输入的占位符
    """
    uid = tf.placeholder(tf.int32, [None, 1], name="uid")
    user_gender = tf.placeholder(tf.int32, [None, 1], name="user_gender")
    user_age = tf.placeholder(tf.int32, [None, 1], name="user_age")
    user_job = tf.placeholder(tf.int32, [None, 1], name="user_job")
    
    return uid, user_gender, user_age, user_job

def get_movie_inputs():
    """
    定义输入的占位符
    """
    movie_id = tf.placeholder(tf.int32, [None, 1], name="movie_id")
    movie_categories = tf.placeholder(tf.int32, [None, 18], name="movie_categories")
    movie_titles = tf.placeholder(tf.int32, [None, 15], name="movie_titles")
    
    return movie_id, movie_categories, movie_titles


def get_user_embedding(uid, user_gender, user_age, user_job):
    """
    定义User的嵌入矩阵
    """
    with tf.name_scope("user_embedding"):
        uid_embed_matrix = tf.Variable(tf.random_uniform([uid_max, embed_dim], -1, 1), name="uid_embed_matrix")
        uid_embed_layer = tf.nn.embedding_lookup( uid_embed_matrix, uid, name="uid_embed_layer")

        gender_embed_matrix = tf.Variable(tf.random_uniform([gender_max, embed_dim // 2], -1, 1), name="gender_embed_matrix")
        gender_embed_layer = tf.nn.embedding_lookup(gender_embed_matrix, user_gender, name="gender_embed_layer")

        age_embed_matrix = tf.Variable(tf.random_uniform([age_max, embed_dim // 2], -1, 1), name="age_embed_matrix")
        age_embed_layer = tf.nn.embedding_lookup(age_embed_matrix, user_age, name="age_embed_layer")

        job_embed_matrix = tf.Variable(tf.random_uniform([job_max, embed_dim // 2], -1, 1), name="job_embed_matrix")
        job_embed_layer = tf.nn.embedding_lookup(job_embed_matrix, user_job, name="job_embed_layer")

    return uid_embed_layer, gender_embed_layer, age_embed_layer, job_embed_layer


def get_user_feature_layer(uid_embed_layer, gender_embed_layer, age_embed_layer, job_embed_layer):
    """
    User 的嵌入矩阵一起全连接生成 User 的特征
    """
    with tf.name_scope("user_fc"):
        #第一层全连接
        uid_fc_layer = tf.layers.dense(uid_embed_layer, embed_dim, name = "uid_fc_layer", activation=tf.nn.relu)
        gender_fc_layer = tf.layers.dense(gender_embed_layer, embed_dim, name = "gender_fc_layer", activation=tf.nn.relu)
        age_fc_layer = tf.layers.dense(age_embed_layer, embed_dim, name ="age_fc_layer", activation=tf.nn.relu)
        job_fc_layer = tf.layers.dense(job_embed_layer, embed_dim, name = "job_fc_layer", activation=tf.nn.relu)
        
        #第二层全连接
        user_combine_layer = tf.concat([uid_fc_layer, gender_fc_layer, age_fc_layer, job_fc_layer], 2)  #(?, 1, 128)
        user_combine_layer = tf.contrib.layers.fully_connected(user_combine_layer, 200, tf.tanh)  #(?, 1, 200)
    
        user_combine_layer_flat = tf.reshape(user_combine_layer, [-1, 200])
    return user_combine_layer, user_combine_layer_flat


def get_movie_id_embed_layer(movie_id):
    """
    定义Movie ID的嵌入矩阵
    """
    with tf.name_scope("movie_embedding"):
        movie_id_embed_matrix = tf.Variable(tf.random_uniform([movie_id_max, embed_dim], -1, 1), name = "movie_id_embed_matrix")
        movie_id_embed_layer = tf.nn.embedding_lookup(movie_id_embed_matrix, movie_id, name = "movie_id_embed_layer")
    return movie_id_embed_layer


def get_movie_categories_layers(movie_categories):
    """
    对电影类型的多个嵌入向量做加和
    """
    with tf.name_scope("movie_categories_layers"):
        movie_categories_embed_matrix = tf.Variable(tf.random_uniform([movie_categories_max, embed_dim], -1, 1), name = "movie_categories_embed_matrix")
        movie_categories_embed_layer = tf.nn.embedding_lookup(movie_categories_embed_matrix, movie_categories, name = "movie_categories_embed_layer")
        if combiner == "sum":
            movie_categories_embed_layer = tf.reduce_sum(movie_categories_embed_layer, axis=1, keep_dims=True)

    return movie_categories_embed_layer


def get_movie_cnn_layer(movie_titles):
    """
    Movie Title的文本卷积网络实现
    """
    #从嵌入矩阵中得到电影名对应的各个单词的嵌入向量
    with tf.name_scope("movie_embedding"):
        movie_title_embed_matrix = tf.Variable(tf.random_uniform([movie_title_max, embed_dim], -1, 1), name = "movie_title_embed_matrix")
        movie_title_embed_layer = tf.nn.embedding_lookup(movie_title_embed_matrix, movie_titles, name = "movie_title_embed_layer")
        movie_title_embed_layer_expand = tf.expand_dims(movie_title_embed_layer, -1)
    
    #对文本嵌入层使用不同尺寸的卷积核做卷积和最大池化
    pool_layer_lst = []
    for window_size in window_sizes:
        with tf.name_scope("movie_txt_conv_maxpool_{}".format(window_size)):
            filter_weights = tf.Variable(tf.truncated_normal([window_size, embed_dim, 1, filter_num],stddev=0.1),name = "filter_weights")
            filter_bias = tf.Variable(tf.constant(0.1, shape=[filter_num]), name="filter_bias")
            # 卷积
            conv_layer = tf.nn.conv2d(movie_title_embed_layer_expand, filter_weights, [1,1,1,1], padding="VALID", name="conv_layer")
            relu_layer = tf.nn.relu(tf.nn.bias_add(conv_layer,filter_bias), name ="relu_layer")
            
            maxpool_layer = tf.nn.max_pool(relu_layer, [1,sentences_size - window_size + 1 ,1,1], [1,1,1,1], padding="VALID", name="maxpool_layer")
            pool_layer_lst.append(maxpool_layer)

    #Dropout层
    with tf.name_scope("pool_dropout"):
        pool_layer = tf.concat(pool_layer_lst, 3, name ="pool_layer")
        max_num = len(window_sizes) * filter_num
        pool_layer_flat = tf.reshape(pool_layer , [-1, 1, max_num], name = "pool_layer_flat")
    
        dropout_layer = tf.nn.dropout(pool_layer_flat, dropout_keep, name = "dropout_layer")
    return pool_layer_flat, dropout_layer


def get_movie_feature_layer(movie_id_embed_layer, movie_categories_embed_layer, dropout_layer):
    """
    将Movie的各个层一起做全连接
    """
    with tf.name_scope("movie_fc"):
        #第一层全连接
        movie_id_fc_layer = tf.layers.dense(movie_id_embed_layer, embed_dim, name = "movie_id_fc_layer", activation=tf.nn.relu)
        movie_categories_fc_layer = tf.layers.dense(movie_categories_embed_layer, embed_dim, name = "movie_categories_fc_layer", activation=tf.nn.relu)
    
        #第二层全连接
        movie_combine_layer = tf.concat([movie_id_fc_layer, movie_categories_fc_layer, dropout_layer], 2)  #(?, 1, 96)
        movie_combine_layer = tf.contrib.layers.fully_connected(movie_combine_layer, 200, tf.tanh)  #(?, 1, 200)

        movie_combine_layer_flat = tf.reshape(movie_combine_layer, [-1, 200])
    return movie_combine_layer, movie_combine_layer_flat


def fit():
    tf.reset_default_graph()
    train_graph = tf.Graph()
    with train_graph.as_default():
        #获取输入占位符
        targets, lr, dropout_keep_prob = get_params_inputs()
        uid, user_gender, user_age, user_job = get_usr_inputs()
        movie_id, movie_categories, movie_titles = get_movie_inputs()
        #获取User的4个嵌入向量
        uid_embed_layer, gender_embed_layer, age_embed_layer, job_embed_layer = get_user_embedding(uid, user_gender, user_age, user_job)
        #得到用户特征
        user_combine_layer, user_combine_layer_flat = get_user_feature_layer(uid_embed_layer, gender_embed_layer, age_embed_layer, job_embed_layer)
        #获取电影ID的嵌入向量
        movie_id_embed_layer = get_movie_id_embed_layer(movie_id)
        #获取电影类型的嵌入向量
        movie_categories_embed_layer = get_movie_categories_layers(movie_categories)
        #获取电影名的特征向量
        pool_layer_flat, dropout_layer = get_movie_cnn_layer(movie_titles)
        #得到电影特征
        movie_combine_layer, movie_combine_layer_flat = get_movie_feature_layer(movie_id_embed_layer,movie_categories_embed_layer,dropout_layer)
        #计算出评分，要注意两个不同的方案，inference的名字（name值）是不一样的，后面做推荐时要根据name取得tensor
        with tf.name_scope("y_pred"):
            y_pred = tf.reduce_sum(user_combine_layer_flat * movie_combine_layer_flat, axis=1)
            y_pred = tf.expand_dims(y_pred, axis=1)

        # 定义损失函数
        with tf.name_scope("loss"):
            # MSE损失，将计算值回归到评分
            cost = tf.losses.mean_squared_error(targets, y_pred)
            loss = tf.reduce_mean(cost)
        # 优化损失 
        #train_op = tf.train.AdamOptimizer(lr).minimize(loss)  #cost
        global_step = tf.Variable(0, name="global_step", trainable=False)
        optimizer = tf.train.AdamOptimizer(lr)
        gradients = optimizer.compute_gradients(loss)  #cost
        train_op = optimizer.apply_gradients(gradients, global_step=global_step)

    print("------------------begin fit ------------------------")
    losses = {'train':[], 'test':[]}
    with tf.Session(graph=train_graph) as sess:
        #搜集数据给tensorBoard用
        # Keep track of gradient values and sparsity
        grad_summaries = []
        for g, v in gradients:
            if g is not None:
                grad_hist_summary = tf.summary.histogram("{}/grad/hist".format(v.name.replace(':', '_')), g)
                sparsity_summary = tf.summary.scalar("{}/grad/sparsity".format(v.name.replace(':', '_')), tf.nn.zero_fraction(g))
                grad_summaries.append(grad_hist_summary)
                grad_summaries.append(sparsity_summary)
        grad_summaries_merged = tf.summary.merge(grad_summaries)
            
        # Output directory for models and summaries
        timestamp = str(int(time.time()))
        out_dir = "./logs/{}".format(timestamp)
        print("Writing to {}\n".format(out_dir))
        
        # Summaries for loss and accuracy
        loss_summary = tf.summary.scalar("loss", loss)

        # Train Summaries
        train_summary_op = tf.summary.merge([loss_summary, grad_summaries_merged])
        train_summary_dir = "{}/summaries/train".format(out_dir)
        train_summary_writer = tf.summary.FileWriter(train_summary_dir, sess.graph)

        # Inference summaries
        inference_summary_op = tf.summary.merge([loss_summary])
        inference_summary_dir = "{}/summaries/inference".format(out_dir)
        inference_summary_writer = tf.summary.FileWriter(inference_summary_dir, sess.graph)

        sess.run(tf.global_variables_initializer())
        saver = tf.train.Saver()
        for epoch_i in range(num_epochs):
            #将数据集分成训练集和测试集，随机种子不固定
            train_X,test_X, train_y, test_y = train_test_split(features,targets_values,test_size = 0.2,random_state = 0)  
            train_batches = get_batches(train_X, train_y, batch_size)
            test_batches = get_batches(test_X, test_y, batch_size)
        
            #训练的迭代，保存训练损失
            for batch_i in range(len(train_X) // batch_size):
                x_train, y_train = next(train_batches)

                categories = np.zeros([batch_size, 18])
                for i in range(batch_size):
                    categories[i] = x_train.take(6,1)[i]

                titles = np.zeros([batch_size, sentences_size])
                for i in range(batch_size):
                    titles[i] = x_train.take(5,1)[i]

                feed = {
                    uid: np.reshape(x_train.take(0, 1), [batch_size, 1]),
                    user_gender: np.reshape(x_train.take(2, 1), [batch_size, 1]),
                    user_age: np.reshape(x_train.take(3, 1), [batch_size, 1]),
                    user_job: np.reshape(x_train.take(4, 1), [batch_size, 1]),
                    movie_id: np.reshape(x_train.take(1, 1), [batch_size, 1]),
                    movie_categories: categories,  # x.take(6,1)
                    movie_titles: titles,  # x.take(5,1)
                    targets: np.reshape(y_train, [batch_size, 1]),
                    dropout_keep_prob: dropout_keep,  # dropout_keep
                    lr: learning_rate}

                step, train_loss, summaries, _ = sess.run([global_step, loss, train_summary_op, train_op], feed)  #cost
                losses['train'].append(train_loss)
                train_summary_writer.add_summary(summaries, step)  #
                
                if (epoch_i * (len(train_X) // batch_size) + batch_i) % show_every_n_batches == 0:
                    time_str = datetime.datetime.now().isoformat()
                    print('{}: Epoch {:>3} Batch {:>4}/{}   train_loss = {:.3f}'.format(
                        time_str, epoch_i,batch_i,(len(train_X) // batch_size),train_loss))
                    
            #使用测试数据的迭代
            for batch_i  in range(len(test_X) // batch_size):
                x_test, y_test = next(test_batches)
                
                categories = np.zeros([batch_size, 18])
                for i in range(batch_size):
                    categories[i] = x_test.take(6,1)[i]

                titles = np.zeros([batch_size, sentences_size])
                for i in range(batch_size):
                    titles[i] = x_test.take(5,1)[i]

                feed = {
                    uid: np.reshape(x_test.take(0, 1), [batch_size, 1]),
                    user_gender: np.reshape(x_test.take(2, 1), [batch_size, 1]),
                    user_age: np.reshape(x_test.take(3, 1), [batch_size, 1]),
                    user_job: np.reshape(x_test.take(4, 1), [batch_size, 1]),
                    movie_id: np.reshape(x_test.take(1, 1), [batch_size, 1]),
                    movie_categories: categories,  # x.take(6,1)
                    movie_titles: titles,  # x.take(5,1)
                    targets: np.reshape(y_test, [batch_size, 1]),
                    dropout_keep_prob: 1,
                    lr: learning_rate}
                
                step, test_loss, summaries = sess.run([global_step, loss, inference_summary_op], feed)  #cost

                #保存测试损失
                losses['test'].append(test_loss)
                inference_summary_writer.add_summary(summaries, step)  #

                time_str = datetime.datetime.now().isoformat()
                if (epoch_i * (len(test_X) // batch_size) + batch_i) % show_every_n_batches == 0:
                    print('{}: Epoch {:>3} Batch {:>4}/{}   test_loss = {:.3f}'.format(
                        time_str,epoch_i,batch_i,(len(test_X) // batch_size),test_loss))

        # Save Model
        saver.save(sess, save_dir)  #, global_step=epoch_i
        print('Model Trained and Saved')
        # 保存参数
        save_params((save_dir))


if __name__ == '__main__':
    fit()

    # uid, user_gender, user_age, user_job = get_usr_inputs()
    # print(uid.shape,user_gender.shape,user_age.shape,user_job.shape)
    # #获取User的4个嵌入向量
    # uid_embed_layer, gender_embed_layer, age_embed_layer, job_embed_layer = get_user_embedding(uid, user_gender, user_age, user_job)
    # print(uid_embed_layer.shape,gender_embed_layer.shape,age_embed_layer.shape,job_embed_layer.shape)
    
    # user_combine_layer, user_combine_layer_flat = get_user_feature_layer(uid_embed_layer, gender_embed_layer, age_embed_layer, job_embed_layer)
    # print(user_combine_layer.shape,user_combine_layer_flat.shape)