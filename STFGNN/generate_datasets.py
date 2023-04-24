import argparse
import pickle
import numpy as np
import os


def generate_graph_seq2seq_io_data(
        data, x_offsets, y_offsets
):
    """
    生成seq2seq样本数据
    :param data: np数据 [B, N, D] 其中D为3
    :param x_offsets:
    :param y_offsets:
    :return:
    """
    num_samples, num_nodes, _ = data.shape
    data = data[:, :, 0:1]  # 只取第一维度的特征

    x, y = [], []
    x_timeslot = []
    y_timeslot = []
    min_t = abs(min(x_offsets))  # 11
    max_t = abs(num_samples - abs(max(y_offsets)))  # num_samples - 12

    for t in range(min_t, max_t):
        x_t = data[t + x_offsets, ...]  # t = 11时, [0,1,2,...,11]
        y_t = data[t + y_offsets, ...]  # t = 11时, [12,13,...,23]

        x.append(x_t)
        y.append(y_t)

        x_timeslot.append((t + x_offsets) % 288)
        y_timeslot.append((t + y_offsets) % 288)  # 记录label的first observation属于哪个时间段

    x = np.stack(x, axis=0)  # [B, T, N ,C]
    y = np.stack(y, axis=0)  # [B ,T, N, C]

    y_timeslot = np.stack(y_timeslot, axis=0)  # (epoch_size, T)
    x_timeslot = np.stack(x_timeslot, axis=0)  # (epoch_size, T)

    return x, y, x_timeslot, y_timeslot


def generate_train_val_test(args, mean_filename):
    """生成数据"""
    data_seq = np.load(args.traffic_df_filename)['data']
    # 交通数据 (sequence_length, num_of_vertices, num_of_features)

    seq_length_x, seq_length_y = args.seq_length_x, args.seq_length_y

    x_offsets = np.arange(-(seq_length_x - 1), 1, 1)
    y_offsets = np.arange(args.y_start, (seq_length_y + 1), 1)

    x, y, x_timeslot, y_timeslot = generate_graph_seq2seq_io_data(data=data_seq, x_offsets=x_offsets,
                                                                  y_offsets=y_offsets)

    # [B, T, N ,C]

    print("x shape: ", x.shape, ", y shape: ", y.shape)
    print("x_timeslot: ", x_timeslot.shape, ", y_timeslot: ", y_timeslot.shape)
    num_samples = x.shape[0]
    num_test = round(num_samples * 0.2)
    num_train = round(num_samples * 0.7)
    num_val = num_samples - num_train - num_test

    # 训练集
    x_train, y_train = x[:num_train], y[:num_train]
    x_timeslot_train = x_timeslot[:num_train]
    y_timeslot_train = x_timeslot[:num_train]  # (len, 12)
    print(x_timeslot_train.shape)

    # 验证集
    x_val, y_val = x[num_train:num_train + num_val], y[num_train:num_train + num_val]
    y_timeslot_val = y_timeslot[num_train: num_train + num_val]
    x_timeslot_val = x_timeslot[num_train: num_train + num_val]
    print(x_timeslot_val.shape)

    # 测试集
    x_test, y_test = x[num_train + num_val:], y[num_train + num_val:]
    y_timeslot_test = y_timeslot[-num_test:]
    x_timeslot_test = x_timeslot[-num_test:]
    print(y_timeslot_test.shape)

    # 改训练集的标签，转换为趋势
    # 计算每个结点在288个时间段的均值
    with open(mean_filename, 'rb') as f:
        pickle_data = pickle.load(f)
    num_nodes, timeslot = pickle_data.shape
    pickle_mean_data = np.reshape(pickle_data, (num_nodes, 7, 288))
    pickle_mean_data = np.mean(pickle_mean_data, axis=1)  # (num_nodes, 288)  # 每个结点在288个时间段的均值

    constant = 5

    # 改训练集的标签，转换为趋势
    x_train_len, T, num_nodes, input_dim = x_train.shape  # (len, 12, num_nodes, 1)
    for index in range(x_train_len):
        x_train_value = x_train[index][T - 1]
        cur_timeslot = x_timeslot_train[index][-1]  # 最后一个时刻对应的时间段, 整数
        indices = []
        for i in range(num_nodes):  # 确定x_train_val为0值的元素所对应的索引
            if x_train_value[i, 0] == 0:
                indices.append(i)

        for ind in indices:
            for t in range(T - 1)[::-1]:  # 把x_train_val为0值所对应的元素往前替换为最新的那个
                if x_train[index][t][ind][0] != 0:
                    x_train_value[ind][0] = x_train[index][t][ind][0]
                    break

        # 如果前面11个数据为0, 则用当前时间段及之前的均值替换0
        for ind in indices:
            if x_train_value[ind, 0] == 0:
                for prev_timeslot in range(cur_timeslot + 1)[::-1]:
                    if pickle_mean_data[ind][prev_timeslot] != 0:  # 如果当前时间段均值为0,则往前寻找非0均值
                        x_train_value[ind][0] = pickle_mean_data[ind][cur_timeslot]
                        break

        # 如果均值也还是0的话,用常数代替
        for ind in indices:
            if x_train_value[ind, 0] == 0:
                x_train_value[ind][0] = constant

        for t in range(T):
            for node in range(num_nodes):
                y_train[index][t][node][0] = (y_train[index][t][node][0] - x_train_value[node][0]) / x_train_value[node][0]

    # 改变验证集和测试集的训练数据
    x_val_len, T, num_nodes, input_dim = x_val.shape  # (len, 12, num_nodes, 1)
    for index in range(x_val_len):
        x_val_value = x_val[index][T - 1]
        cur_timeslot = x_timeslot_val[index][-1]  # 最后一个时刻对应的时间段, 整数
        indices = []
        for i in range(num_nodes):  # 确定x_val_value为0值的元素所对应的索引
            if x_val_value[i, 0] == 0:
                indices.append(i)

        for ind in indices:
            for t in range(T - 1)[::-1]:
                if x_val[index][t][ind][0] != 0:
                    x_val_value[ind][0] = x_val[index][t][ind][0]
                    break

        # 如果前面11个数据为0, 则用当前时间段及之前的均值替换0
        for ind in indices:
            if x_val_value[ind, 0] == 0:
                for prev_timeslot in range(cur_timeslot + 1)[::-1]:
                    if pickle_mean_data[ind][prev_timeslot] != 0:
                        x_val_value[ind][0] = pickle_mean_data[ind][cur_timeslot]
                        break

        # 如果均值也还是0的话,用常数代替
        for ind in indices:
            if x_val_value[ind, 0] == 0:
                x_val_value[ind][0] = constant

    x_test_len, T, num_nodes, input_dim = x_test.shape  # (len, 12, num_nodes, 1)
    for index in range(x_test_len):
        x_test_value = x_test[index][T - 1]
        cur_timeslot = x_timeslot_test[index][-1]  # 最后一个时刻对应的时间段, 整数
        indices = []
        for i in range(num_nodes):  # 确定x_val_value为0值的元素所对应的索引
            if x_test_value[i, 0] == 0:
                indices.append(i)

        for ind in indices:
            for t in range(T - 1)[::-1]:
                if x_test[index][t][ind][0] != 0:
                    x_test_value[ind][0] = x_test[index][t][ind][0]
                    break

        # 如果前面11个数据为0, 则用当前时间段及之前的均值替换0
        for ind in indices:
            if x_test_value[ind, 0] == 0:
                for prev_timeslot in range(cur_timeslot + 1)[::-1]:
                    if pickle_mean_data[ind][prev_timeslot] != 0:
                        x_test[ind][0] = pickle_mean_data[ind][cur_timeslot]
                        break

        # 如果均值也还是0的话,用常数代替
        for ind in indices:
            if x_test_value[ind, 0] == 0:
                x_test_value[ind][0] = constant

    for cat in ['train', 'val', 'test']:
        _x, _y = locals()["x_" + cat], locals()["y_" + cat]
        _y_slot = locals()["y_timeslot_" + cat]
        _x_slot = locals()["x_timeslot_" + cat]
        # local() 是当前def中的所有变量构成的字典

        print(cat, "x: ", _x.shape, "y:", _y.shape, "y_slot:", _y_slot.shape)
        np.savez_compressed(
            # 保存多个数组，按照你定义的key字典保存，compressed表示它是一个压缩文件
            os.path.join(args.output_dir, f"{cat}.npz"),
            x=_x,
            y=_y,
            x_slot=_x_slot,
            y_slot=_y_slot,
            x_offsets=x_offsets.reshape(list(x_offsets.shape) + [1]),  # shape从原来的(12,) 转为(12,1)
            y_offsets=y_offsets.reshape(list(y_offsets.shape) + [1]),  # shape从原来的(12,) 转为(12,1)
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output_dir', type=str, default="../data/processed/PEMS08/", help="输出文件夹")
    parser.add_argument('--flow_mean', type=str, default="../data/PEMS08/PEMS08_flow_count.pkl", help="均值流量文件")
    parser.add_argument('--traffic_df_filename', type=str, default="../data/PEMS08/PEMS08.npz", help="数据集")
    parser.add_argument('--seq_length_x', type=int, default=12, help='输入序列长度')
    parser.add_argument('--seq_length_y', type=int, default=12, help='输出序列长度')
    parser.add_argument('--y_start', type=int, default=1, help='从第几天开始预测')

    args = parser.parse_args()
    mean_flow_file = args.flow_mean
    if os.path.exists(args.output_dir):
        reply = str(input(f'{args.output_dir} 存在，是否将其作为输出目录?(y/n)')).lower().strip()
        if reply[0] != 'y':
            exit()
    else:
        os.makedirs(args.output_dir)
    generate_train_val_test(args, mean_flow_file)

"""
PEMS04:
x shape:  (16969, 12, 307, 1) , y shape:  (16969, 12, 307, 1)
train x:  (10181, 12, 307, 1) y: (10181, 12, 307, 1)
val x:  (3394, 12, 307, 1) y: (3394, 12, 307, 1)
test x:  (3394, 12, 307, 1) y: (3394, 12, 307, 1)

PEMSO8:
x shape:  (17833, 12, 170, 1) , y shape:  (17833, 12, 170, 1)
train x:  (10700, 12, 170, 1) y: (10700, 12, 170, 1)
val x:  (3566, 12, 170, 1) y: (3566, 12, 170, 1)
test x:  (3567, 12, 170, 1) y: (3567, 12, 170, 1)
"""
