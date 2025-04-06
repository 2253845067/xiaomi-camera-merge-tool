import argparse
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta

# 设置日志配置为INFO级别
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def extract_date_from_filename(file_name):
    match = re.search(r"(\d{8})", file_name)
    if match:
        return match.group(1)
    return None


def merge_videos(input_folder, output_folder, delete_old_videos):
    input_folder = input_folder.encode('gbk').decode('gb2312')
    logging.info(f"Starting video merging process..., input is {input_folder}")
    # 确保输出文件夹存在
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logging.info(f"Created output directory at {output_folder}")

    # 存储视频文件的字典，键为文件名最前面的日期，值为视频文件路径列表
    videos_dict = {}
    exist_videos_dict = {}
    for file_name in os.listdir(output_folder):
        if file_name.endswith(('.mp4', '.avi', '.mov')):  # 检查文件扩展名
            date_prefix = extract_date_from_filename(file_name)
            if date_prefix:
                logging.info(f"Found exist video {file_name} with date prefix {date_prefix}")
                video_path = os.path.join(output_folder, file_name)
                if date_prefix in exist_videos_dict:
                    exist_videos_dict[date_prefix].append(video_path)
                else:
                    exist_videos_dict[date_prefix] = [video_path]

    # 从输出路径中最近的日期开始合并新的文件
    max_date = None  # 用于存储最大日期的键
    for key in exist_videos_dict:
        try:
            # 尝试将键解析为日期
            current_file_date = datetime.strptime(key, "%Y%m%d")
            # 更新最大日期
            if max_date is None or current_file_date > max_date:
                max_date = current_file_date
        except ValueError:
            logging.warning(f"Invalid date format in key: {key}")

    if max_date:
        max_date_str = max_date.strftime("%Y%m%d")
        print(f"最大日期是: {max_date_str}")
    else:
        print("未找到有效的日期键。")

    if delete_old_videos:
        # 删除一周之前的视频
        logging.info("Cleaning up videos older than two weeks...")
        weeks_ago = datetime.now() - timedelta(weeks=1)
        for file_name in os.listdir(output_folder):
            if file_name.endswith(('.mp4', '.avi', '.mov')):
                try:
                    old_file_date = extract_date_from_filename(file_name)
                    if old_file_date:
                        video_date = datetime.strptime(old_file_date, "%Y%m%d")
                        if video_date < weeks_ago:
                            video_path = os.path.join(output_folder, file_name)
                            os.remove(video_path)
                            logging.info(f"Deleted old video: {video_path}")
                except ValueError:
                    logging.warning(f"Invalid date format in file name: {file_name}")

    # 收集需要合并的小视频列表
    for file_name in os.listdir(input_folder):
        if file_name.endswith(('.mp4', '.avi', '.mov')):  # 检查文件扩展名
            key = extract_date_from_filename(file_name)
            if key:
                current_file_date = datetime.strptime(key, "%Y%m%d")
                today_date = datetime.now().date()
                if current_file_date.date() == today_date:
                    logging.info(f"Skipping today's video {file_name}")
                    continue
                if key not in exist_videos_dict and ( max_date is None or current_file_date > max_date):
                    video_path = os.path.join(input_folder, file_name)
                    logging.info(f"Found video {file_name} with prefix {key}")
                    if key in videos_dict:
                        videos_dict[key].append(video_path)
                    else:
                        videos_dict[key] = [video_path]
                else:
                    print('Skip merge video ', file_name, 'due to already exist. ')

    # 合并视频
    for key, video_paths in videos_dict.items():
        logging.info(f"Merging videos with prefix {key}...")
        # 创建一个临时文件列表
        tmp_file = os.path.join(output_folder, f"tmp_{key}.txt")
        with open(tmp_file, 'w') as f:
            for video_path in video_paths:
                f.write(f"file '{video_path}'\n")

        # 使用ffmpeg合并视频
        output_path = os.path.join(output_folder, f"{key}_merged.mp4")
        cmd = f"ffmpeg -f concat -safe 0 -i {tmp_file} -c copy {output_path}"
        subprocess.run(cmd, shell=True, check=True)
        logging.info(f"Merged video saved to {output_path}")

        # 删除临时文件
        os.remove(tmp_file)
        logging.info(f"Temporary file {tmp_file} deleted")

    logging.info("Video merging process completed.")

def main():
    parser = argparse.ArgumentParser(description="Merge videos with the same prefix using ffmpeg.")
    parser.add_argument("--input", type=str, help="Input folder path containing videos", required=True)
    parser.add_argument("--output", type=str, help="Output folder path for merged videos", required=True)
    parser.add_argument("--delete-old-videos", action="store_true", help="Delete videos older than two weeks (default: False)")
    args = parser.parse_args()

    merge_videos(args.input, args.output, args.delete_old_videos)

if __name__ == "__main__":
    main()