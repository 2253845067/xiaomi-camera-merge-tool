import os
import argparse
import subprocess
import logging
import sys


# 设置日志配置为INFO级别
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def merge_videos(input_folder, output_folder):
    input_folder = input_folder.encode('gbk').decode('gb2312')
    logging.info(f"Starting video merging process..., input is {input_folder}")
    # 确保输出文件夹存在
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logging.info(f"Created output directory at {output_folder}")

    # 存储视频文件的字典，键为文件名前8个字符，值为视频文件路径列表
    videos_dict = {}
    exist_videos_dict = {}
    for file_name in os.listdir(output_folder):
        if file_name.endswith(('.mp4', '.avi', '.mov')):  # 检查文件扩展名
            exist_key = file_name[:8]  # 获取文件名前8个字符
            logging.info(f"Found exsit video {file_name} with prefix {exist_key}")
            video_path = os.path.join(output_folder, file_name)
            if exist_key in exist_videos_dict:
                exist_videos_dict[exist_key].append(video_path)
            else:
                exist_videos_dict[exist_key] = [video_path]
    from datetime import datetime

    # 假设文件名前8个字符是日期，格式为 YYYYMMDD
    max_date = None  # 用于存储最大日期的键

    for key in exist_videos_dict:
        try:
            # 尝试将键解析为日期
            current_date = datetime.strptime(key, "%Y%m%d")
            # 更新最大日期
            if max_date is None or current_date > max_date:
                max_date = current_date
        except ValueError:
            logging.warning(f"Invalid date format in key: {key}")

    if max_date:
        max_date_str = max_date.strftime("%Y%m%d")
        print(f"最大日期是: {max_date_str}")
    else:
        print("未找到有效的日期键。")
    # 遍历文件夹中的所有文件
    for file_name in os.listdir(input_folder):
        if file_name.endswith(('.mp4', '.avi', '.mov')) and not file_name.startswith('2024110608'):  # 检查文件扩展名
            key = file_name[:8]  # 获取文件名前8个字符
            current_date = datetime.strptime(key, "%Y%m%d")
            if key not in exist_videos_dict and (max_date is None or current_date > max_date):
                video_path = os.path.join(input_folder, file_name)
                logging.info(f"Found video {file_name} with prefix {key}")
                if key in videos_dict:
                    videos_dict[key].append(video_path)
                else:
                    videos_dict[key] = [video_path]
            else:
                print('Skip merge video ', key, 'due to already exsit. ')

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
    
    args = parser.parse_args()

    merge_videos(args.input, args.output)

if __name__ == "__main__":
    main()
