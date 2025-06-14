import os
import glob
import time
import random
import datetime
from pathlib import Path

import numpy as np
# from cv2 import *
from numpy import array, reshape, where, mean, argmax
from pandas import read_csv
import cv2


file_path = "data/20200626_154313_mlx90640_01_light_none.csv"


def get_label(f_path, label_name="20200626_154313_mlx90640_01_light_none.csv", query_start=10, query_end=65):
    query_end = query_end - 1
    try:
        with open(f_path, 'r') as file:
            for line in file:
                if line.startswith(label_name + ','):
                    parts = line.strip().split(',')
                    labels = {}
                    for i in range(1, len(parts), 3):
                        if i + 2 >= len(parts):
                            continue
                        try:
                            s0 = int(parts[i])
                            e0 = int(parts[i+1])
                            act = parts[i+2].strip()
                        except (ValueError, IndexError):
                            continue

                        if not act or act.lower() == 'none':
                            continue

                        if max(s0, query_start) < min(e0, query_end):
                            s = max(s0, query_start)
                            e = min(e0, query_end)
                            
                            if s < e:
                                labels[(s, e)] = act
                    return labels
        return {}
    except FileNotFoundError:
        print(f"错误: 文件未找到 {f_path}")
        return {}


def data2frame(data):
    out_data = cv2.normalize(data, None, 0, 255, cv2.NORM_MINMAX)
    frame = (out_data).astype('uint8')
    return frame


# get data via given number frames
def get_data(f_path, num_frame=256):
    df = read_csv(f_path, index_col=False)
    start_pos = random.randint(0, len(df) - num_frame)
    end_pos = start_pos + num_frame
    data = df.iloc[:, 2:].values[start_pos:end_pos].reshape((num_frame, 24, 32))
    # extract and parse time strings to datetime objects
    timestamp_dt = [datetime.datetime.fromisoformat(ts) for ts in df.iloc[:, 0].values[start_pos:end_pos]]
    # reset timestamp to start from 0
    ts_0 = timestamp_dt[0]
    timestamp = [(ts - ts_0).total_seconds() for ts in timestamp_dt]
    print("timestamp: ", timestamp)


    # _mean = mean(data)
    # data = where(data > _mean*1.050, data, 0)
    # data = cv2.normalize(data, None, 0, 255, cv2.NORM_MINMAX)
    # padding to 32x32 
    # data = np.pad(data, ((0, 0), (4, 4), (0, 0)), mode='constant', constant_values=0)
    return data, (start_pos, end_pos), timestamp


def show_data(data):
    unique_values = np.unique(data)
    # print("unique values: ", unique_values)
    num_frames = data.shape[0]
    rows = 16
    cols = (num_frames + rows - 1) // rows  # Calculate columns needed

    # Create an empty image to hold all frames
    combined_image = np.zeros((rows * 24, cols * 32), dtype=np.uint8)

    for i in range(num_frames):
        frame = data2frame(data[i])
        row_idx = i % rows
        col_idx = i // rows
        combined_image[row_idx * 24:(row_idx + 1) * 24, col_idx * 32:(col_idx + 1) * 32] = frame

    cv2.imshow("Combined Frames", combined_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":

    label_path = "D:/projects/FIR-Image-Action-Dataset/labels/labels.csv"
    # labels = get_label(label_path)

    data, (start_pos, end_pos), timestamp = get_data(file_path)
    labels = get_label(label_path, label_name=os.path.basename(file_path), query_start=start_pos, query_end=end_pos)
    # fix offset
    labels = { (s-start_pos, e-start_pos): act for (s, e), act in labels.items() }
    print("Labels before timestamp replacement: ", labels)
    # replace idx to timestamp
    labels = { (timestamp[s], timestamp[e]): act for (s, e), act in labels.items() }

    print("Labels: ", labels)
    print("data shape: ", data.shape)

    start_time = time.time()
    show_data(data)
    end_time = time.time()
    print("Time taken to display data: {:.2f} seconds".format(end_time - start_time))
