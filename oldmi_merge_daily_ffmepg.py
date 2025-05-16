import os
import subprocess
from datetime import datetime
from collections import defaultdict
import argparse


def merge_videos(input_path, output_path):
    # 检查输出路径是否存在，如果不存在则创建
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # 按日期分组存储视频文件
    daily_videos = defaultdict(list)

    # 获取今天的日期
    today = datetime.now().strftime("%Y%m%d")

    # 遍历输入路径中的所有文件夹
    for folder_name in os.listdir(input_path):
        folder_path = os.path.join(input_path, folder_name)

        # 确保是文件夹
        if os.path.isdir(folder_path):
            try:
                # 解析文件夹名称，提取日期和小时
                folder_date = datetime.strptime(folder_name, "%Y%m%d%H")
                date_str = folder_date.strftime("%Y%m%d")  # 日期字符串，用于分组
            except ValueError:
                # 如果文件夹名称不符合格式，跳过
                print(f"Skipping invalid folder name: {folder_name}")
                continue

            # 跳过今天的视频
            if date_str == today:
                print(f"Skipping today's folder: {folder_name}")
                continue

            # 获取该文件夹内所有视频文件
            video_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if
                           f.endswith(('.mp4', '.avi', '.mov'))]

            # 提取时间戳并排序
            video_files.sort(key=lambda x: int(os.path.splitext(os.path.basename(x).split('_')[-1])[0]))

            if not video_files:
                print(f"No video files found in folder: {folder_name}")
                continue

            # 将视频文件添加到对应日期的列表中
            daily_videos[date_str].extend(video_files)

    # 合并每天的视频
    for date, video_list in daily_videos.items():
        daily_output_file = os.path.join(output_path, f"{date}_daily_merged.mp4")

        # 检查是否已经合并过
        if os.path.exists(daily_output_file):
            print(f"Skipping already merged file: {daily_output_file}")
            continue

        # 创建 FFmpeg 的输入文件列表
        daily_filelist_path = os.path.join(output_path, "daily_filelist.txt")
        with open(daily_filelist_path, "w") as filelist:
            for video_file in video_list:
                filelist.write(f"file '{video_file}'\n")

        merge_command = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", daily_filelist_path,  # 使用 output_path 下的文件列表
            "-c:v", "copy",
            daily_output_file
        ]

        # 调用 FFmpeg 合并视频
        subprocess.run(merge_command)

        print(f"Merged daily video saved to: {daily_output_file}")

        # 清理临时文件
        os.remove(daily_filelist_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge hourly video files into daily video files.")
    parser.add_argument("--input", type=str, help="Path to the input folder containing hourly video folders.")
    parser.add_argument("--output", type=str,
                        help="Path to the output folder where daily merged videos will be saved.")
    args = parser.parse_args()

    merge_videos(args.input, args.output)