import argparse
import logging
import os
import re
import subprocess
import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict

# 设置日志配置为INFO级别
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ---- 大小与压缩相关工具 ----
MAX_BYTES_5G = 5 * 1024**3  # 5GB（二进制，若想十进制请改为 5_000_000_000）

def _get_duration_seconds(path):
    """用 ffprobe 读时长（秒）。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        ).stdout.strip()
        return float(out)
    except Exception as e:
        logging.error(f"ffprobe 获取时长失败: {e}")
        return None

def _get_audio_bitrate_kbps_sum(path):
    """
    返回所有音频轨道的总码率（Kbps）。若无法读取（VBR 无 bit_rate 等），返回 None。
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=bit_rate", "-of", "json", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        ).stdout
        data = json.loads(out)
        streams = data.get("streams", [])
        total = 0
        valid = False
        for s in streams:
            br = s.get("bit_rate")
            if br is not None:
                try:
                    br_int = int(br)
                    if br_int > 0:
                        total += br_int
                        valid = True
                except Exception:
                    pass
        if valid:
            return int(total / 1000)  # 转 Kbps
        return None
    except Exception as e:
        logging.warning(f"无法读取音频码率（可能是VBR）：{e}")
        return None

def _cleanup_pass_logs(log_prefix):
    """清理两遍编码的日志文件。"""
    for f in glob.glob(f"{log_prefix}*"):
        try:
            os.remove(f)
        except Exception:
            pass

def _two_pass_reencode_keep_audio(src, dst_tmp, video_kbps, passlog_prefix):
    """
    两遍编码，仅重压视频（libx264），音频不动（copy）。
    第一遍丢弃输出到空设备。
    """
    devnull = os.devnull
    # pass 1
    cmd1 = [
        "ffmpeg", "-y", "-i", src,
        "-c:v", "libx264", "-b:v", f"{video_kbps}k",
        "-pass", "1", "-preset", "medium", "-an",
        "-f", "mp4", "-passlogfile", passlog_prefix, devnull
    ]
    # pass 2
    cmd2 = [
        "ffmpeg", "-y", "-i", src,
        "-c:v", "libx264", "-b:v", f"{video_kbps}k",
        "-pass", "2", "-preset", "medium",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-passlogfile", passlog_prefix, dst_tmp
    ]
    logging.info(f"[2-pass] 视频码率={video_kbps}k，音频copy")
    subprocess.run(cmd1, check=True)
    subprocess.run(cmd2, check=True)
    _cleanup_pass_logs(passlog_prefix)

def _iterative_crf_keep_audio(src, dst_tmp, max_bytes, start_crf=23, step=2, max_crf=35):
    """
    迭代 CRF，在不改动音频的情况下寻找小于 max_bytes 的体积。
    返回 (是否成功, 最终生成文件大小)
    """
    crf = start_crf
    best_size = None
    best_path = None

    while crf <= max_crf:
        try:
            logging.info(f"[CRF迭代] 尝试 CRF={crf}（音频copy）")
            subprocess.run([
                "ffmpeg", "-y", "-i", src,
                "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
                "-c:a", "copy",
                "-movflags", "+faststart",
                dst_tmp
            ], check=True)
            size_now = os.path.getsize(dst_tmp)
            if best_size is None or size_now < best_size:
                best_size = size_now
            if size_now <= max_bytes:
                return True, size_now
            # 未达标，增大 CRF 继续
            crf += step
        except subprocess.CalledProcessError as e:
            logging.warning(f"CRF={crf} 失败: {e}")
            crf += step

    return False, best_size if best_size is not None else 0

def compress_if_needed(path, max_bytes=MAX_BYTES_5G, safety=0.95, min_video_kbps=300, max_retries=2):
    """
    若文件超过 max_bytes，就在不动音频的前提下压缩：
    1) 能读取音频总码率 -> 用两遍码率法精确控体积（更接近目标大小）
    2) 否则退化为 CRF 迭代（音频copy）

    safety: 安全系数，防止容器开销导致略超
    max_retries: 2-pass 若首次仍略超，继续递减码率重试的次数
    """
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        logging.error(f"文件不存在，无法压缩: {path}")
        return

    if size <= max_bytes:
        logging.info(f"合并结果未超过阈值({max_bytes} bytes)，无需压缩: {path}")
        return

    dur = _get_duration_seconds(path)
    if not dur or dur <= 0:
        logging.warning(f"无法读取时长，改用 CRF 迭代方案。")
        # 无法读取时长，只能 CRF 迭代
        tmp_out = path + ".tmp.mp4"
        ok, new_size = _iterative_crf_keep_audio(path, tmp_out, max_bytes)
        if ok:
            os.replace(tmp_out, path)
            logging.info(f"压缩完成（CRF），最终大小 {new_size/(1024**3):.2f} GB。")
        else:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            logging.warning("CRF 迭代未能降到阈值以下，保留原文件。")
        return

    audio_kbps = _get_audio_bitrate_kbps_sum(path)
    if audio_kbps is None:
        logging.info("音频码率不可得，改用 CRF 迭代方案（音频copy）。")
        tmp_out = path + ".tmp.mp4"
        ok, new_size = _iterative_crf_keep_audio(path, tmp_out, max_bytes)
        if ok:
            os.replace(tmp_out, path)
            logging.info(f"压缩完成（CRF），最终大小 {new_size/(1024**3):.2f} GB。")
        else:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            logging.warning("CRF 迭代未能降到阈值以下，保留原文件。")
        return

    # 计算目标“总”码率，并为视频分配码率（音频copy）
    target_bits = int(max_bytes * 8 * safety)  # 留安全余量
    total_kbps = target_bits / dur / 1000.0
    video_kbps = max(min_video_kbps, int(total_kbps - audio_kbps))
    if video_kbps <= min_video_kbps:
        logging.info("音频占比偏大，视频预算受限，可能画质较低。")

    base_dir = os.path.dirname(path)
    base_name = os.path.basename(path)
    passlog_prefix = os.path.join(base_dir, f".2pass_{base_name}")
    tmp_out = path + ".tmp.mp4"

    # 首次两遍编码
    try:
        _two_pass_reencode_keep_audio(path, tmp_out, video_kbps, passlog_prefix)
    except subprocess.CalledProcessError as e:
        _cleanup_pass_logs(passlog_prefix)
        logging.error(f"两遍压缩失败，改用 CRF 迭代。错误: {e}")
        ok, new_size = _iterative_crf_keep_audio(path, tmp_out, max_bytes)
        if ok:
            os.replace(tmp_out, path)
            logging.info(f"压缩完成（CRF），最终大小 {new_size/(1024**3):.2f} GB。")
        else:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            logging.warning("CRF 迭代未能降到阈值以下，保留原文件。")
        return

    tries = 0
    while os.path.getsize(tmp_out) > max_bytes and tries < max_retries:
        tries += 1
        # 每次降 15%
        video_kbps = max(min_video_kbps, int(video_kbps * 0.85))
        logging.info(f"仍超出上限，降低视频码率后重试({tries}/{max_retries})，新视频码率={video_kbps}k")
        try:
            _two_pass_reencode_keep_audio(path, tmp_out, video_kbps, passlog_prefix)
        except subprocess.CalledProcessError as e:
            logging.error(f"两遍压缩重试失败: {e}")
            break

    try:
        new_size = os.path.getsize(tmp_out)
        if new_size <= max_bytes:
            os.replace(tmp_out, path)
            logging.info(f"压缩完成（2-pass），最终大小 {new_size/(1024**3):.2f} GB，已替换原文件。")
        else:
            # 两遍仍未达标，尝试 CRF 兜底
            logging.info("两遍压缩仍未达标，改用 CRF 兜底方案。")
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            ok, new_size = _iterative_crf_keep_audio(path, tmp_out, max_bytes)
            if ok:
                os.replace(tmp_out, path)
                logging.info(f"压缩完成（CRF兜底），最终大小 {new_size/(1024**3):.2f} GB。")
            else:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
                logging.warning("CRF 兜底也未能降到阈值以下，保留原文件。")
    except Exception as e:
        logging.error(f"替换/清理文件出错：{e}")
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except Exception:
            pass

# ---- 原脚本功能 ----

def extract_date_from_filename(file_name):
    match = re.search(r"(\d{8})", file_name)
    if match:
        return match.group(1)
    return None

def extract_start_time_from_filename(file_name):
    match = re.search(r"(\d{14})", file_name)
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
        print(f"最大日期是: {max_date_str}, 将从此日期后合并新视频")
    else:
        print("未找到有效的日期键。")

    if delete_old_videos:
        # 删除一周之前的视频
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
                if key not in exist_videos_dict and (max_date is None or current_file_date > max_date):
                    video_path = os.path.join(input_folder, file_name)
                    logging.info(f"Found video {file_name} with prefix {key}")
                    if key in videos_dict:
                        videos_dict[key].append(video_path)
                    else:
                        videos_dict[key] = [video_path]
                else:
                    print('Skip merge video ', file_name, 'due to already exist. ')

    # 对每个日期的视频列表按时间戳排序
    for key, video_paths in videos_dict.items():
        # 提取文件名中的开始时间戳并排序
        sorted_video_paths = sorted(video_paths, key=lambda x: extract_start_time_from_filename(os.path.basename(x)))
        videos_dict[key] = sorted_video_paths
        logging.info(f"Sorted video paths for date {key}: {sorted_video_paths}")

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

        # 若超过 5GB，压缩（不动音频）
        compress_if_needed(output_path, max_bytes=MAX_BYTES_5G)

    logging.info("Video merging process completed.")

def merge_old_cam_videos(input_path, output_path):
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
            "-c:a", "copy",
            daily_output_file
        ]

        # 调用 FFmpeg 合并视频
        subprocess.run(merge_command)

        print(f"Merged daily video saved to: {daily_output_file}")

        # 清理临时文件
        os.remove(daily_filelist_path)

        # 若超过 5GB，压缩（不动音频）
        compress_if_needed(daily_output_file, max_bytes=MAX_BYTES_5G)

def main():
    parser = argparse.ArgumentParser(description="Merge videos with the same prefix using ffmpeg.")
    parser.add_argument("--input", type=str, help="Input folder path containing videos", required=True)
    parser.add_argument("--output", type=str, help="Output folder path for merged videos", required=True)
    parser.add_argument("--delete-old-videos", action="store_true", help="Delete videos older than two weeks (default: False)")
    parser.add_argument("--old-cam", action="store_true",help="is  (default: False)")
    args = parser.parse_args()
    if args.old_cam:
        logging.info("start merging with old camera.")
        merge_old_cam_videos(args.input, args.output)
    else:
        logging.info("start merging with new camera.")
        merge_videos(args.input, args.output, args.delete_old_videos)

if __name__ == "__main__":
    main()
