import argparse
import logging
import os
import re
import subprocess
import json
import glob
import tempfile
from datetime import datetime, timedelta

# 设置日志配置为INFO级别
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ---- 大小与压缩相关工具 ----
VERSION = "4.0.3"
MAX_BYTES_5G = 5 * 1024**3  # 5GB（二进制，若想十进制请改为 5_000_000_000）
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov")
FFMPEG_BASE_CMD = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]


def is_video_file(file_name):
    return file_name.lower().endswith(VIDEO_EXTENSIONS)


def _escape_concat_path(path):
    normalized_path = os.path.abspath(path).replace("\\", "/")
    return normalized_path.replace("'", "'\\''")


def create_concat_file(video_paths, output_folder, prefix):
    tmp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        suffix=".txt",
        prefix=prefix,
        dir=output_folder,
        delete=False,
    )
    try:
        with tmp_file:
            for video_path in video_paths:
                tmp_file.write(f"file '{_escape_concat_path(video_path)}'\n")
        return tmp_file.name
    except Exception:
        try:
            os.remove(tmp_file.name)
        except OSError:
            pass
        raise


def create_temp_mp4(output_folder, prefix):
    tmp_file = tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".mp4",
        prefix=prefix,
        dir=output_folder,
        delete=False,
    )
    tmp_file.close()
    return tmp_file.name


def cleanup_file(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logging.warning(f"Failed to delete temporary file {path}: {e}")

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
        *FFMPEG_BASE_CMD, "-i", src,
        "-c:v", "libx264", "-b:v", f"{video_kbps}k",
        "-pass", "1", "-preset", "medium", "-an",
        "-f", "mp4", "-passlogfile", passlog_prefix, devnull
    ]
    # pass 2
    cmd2 = [
        *FFMPEG_BASE_CMD, "-i", src,
        "-c:v", "libx264", "-b:v", f"{video_kbps}k",
        "-pass", "2", "-preset", "medium",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-passlogfile", passlog_prefix, dst_tmp
    ]
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

    while crf <= max_crf:
        try:
            subprocess.run([
                *FFMPEG_BASE_CMD, "-i", src,
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

def ensure_max_size(path, max_bytes=MAX_BYTES_5G, safety=0.95, min_video_kbps=300, max_retries=2):
    """
    确保文件不超过 max_bytes。若超过，就在不动音频的前提下压缩：
    1) 能读取音频总码率 -> 用两遍码率法精确控体积（更接近目标大小）
    2) 否则退化为 CRF 迭代（音频copy）

    压缩后仍超过 max_bytes 时抛出 RuntimeError，避免留下超限文件却误认为成功。

    safety: 安全系数，防止容器开销导致略超
    max_retries: 2-pass 若首次仍略超，继续递减码率重试的次数
    """
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        raise RuntimeError(f"文件不存在，无法检查大小: {path}") from None

    if size <= max_bytes:
        logging.info(f"合并结果 {size/(1024**3):.2f} GB，未超过 5GB，无需压缩。")
        return

    logging.info(f"合并结果 {size/(1024**3):.2f} GB，超过 5GB，开始压缩。")
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
            raise RuntimeError(f"CRF 迭代未能将文件压缩到 {max_bytes/(1024**3):.2f} GB 以下: {path}")
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
            raise RuntimeError(f"CRF 迭代未能将文件压缩到 {max_bytes/(1024**3):.2f} GB 以下: {path}")
        return

    # 计算目标“总”码率，并为视频分配码率（音频copy）
    target_bits = int(max_bytes * 8 * safety)  # 留安全余量
    total_kbps = target_bits / dur / 1000.0
    video_kbps = max(min_video_kbps, int(total_kbps - audio_kbps))
    if video_kbps <= min_video_kbps:
        logging.info("音频占比偏大，视频预算受限，可能画质较低。")
    logging.info(f"使用 2-pass 压缩，目标视频码率 {video_kbps}k，音频保持 copy。")

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
            raise RuntimeError(f"CRF 迭代未能将文件压缩到 {max_bytes/(1024**3):.2f} GB 以下: {path}")
        return

    tries = 0
    two_pass_failed = False
    while os.path.getsize(tmp_out) > max_bytes and tries < max_retries:
        tries += 1
        # 每次降 15%
        video_kbps = max(min_video_kbps, int(video_kbps * 0.85))
        logging.info(f"仍超出上限，降低视频码率后重试({tries}/{max_retries})，新视频码率={video_kbps}k")
        try:
            _two_pass_reencode_keep_audio(path, tmp_out, video_kbps, passlog_prefix)
        except subprocess.CalledProcessError as e:
            _cleanup_pass_logs(passlog_prefix)
            logging.error(f"两遍压缩重试失败: {e}")
            two_pass_failed = True
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            break

    try:
        new_size = os.path.getsize(tmp_out) if os.path.exists(tmp_out) else max_bytes + 1
        if not two_pass_failed and new_size <= max_bytes:
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
                raise RuntimeError(f"CRF 兜底也未能将文件压缩到 {max_bytes/(1024**3):.2f} GB 以下: {path}")
    except RuntimeError:
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except Exception:
            pass
        raise RuntimeError(f"压缩或清理文件出错: {e}") from e

# ---- 视频合并功能 ----

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

def extract_output_key_from_filename(file_name):
    match = re.fullmatch(r"(\d{8}-(?:AM|PM))\.mp4", file_name)
    if match:
        return match.group(1)
    return None

def extract_half_day_from_start_time(start_time):
    hour = int(start_time[8:10])
    return "AM" if hour < 12 else "PM"

def merge_videos(input_folder, output_folder, delete_old_videos, compress):
    input_folder = os.path.abspath(input_folder)
    output_folder = os.path.abspath(output_folder)
    logging.info(f"开始合并视频，输入目录: {input_folder}")
    logging.info(f"输出目录: {output_folder}")
    # 确保输出文件夹存在
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logging.info(f"已创建输出目录: {output_folder}")

    # 存储视频文件的字典，键为 YYYYMMDD-AM/PM，值为视频文件路径列表
    videos_dict = {}
    exist_videos_dict = {}
    for file_name in os.listdir(output_folder):
        if is_video_file(file_name):  # 检查文件扩展名
            output_key = extract_output_key_from_filename(file_name)
            if output_key:
                video_path = os.path.join(output_folder, file_name)
                if output_key in exist_videos_dict:
                    exist_videos_dict[output_key].append(video_path)
                else:
                    exist_videos_dict[output_key] = [video_path]

    # 记录输出路径中已经合并过的日期，后续只补合并缺失日期。
    max_date = None  # 用于存储最大日期的键
    for key in exist_videos_dict:
        try:
            # 尝试将键解析为日期
            current_file_date = datetime.strptime(key[:8], "%Y%m%d")
            # 更新最大日期
            if max_date is None or current_file_date > max_date:
                max_date = current_file_date
        except ValueError:
            logging.warning(f"Invalid date format in key: {key}")

    if max_date:
        max_date_str = max_date.strftime("%Y%m%d")
        logging.info(f"已存在视频的最大日期: {max_date_str}")
    else:
        logging.info("输出目录中暂未发现已合并的日期文件。")

    if delete_old_videos:
        # 删除一周之前的视频
        weeks_ago = datetime.now() - timedelta(weeks=1)
        for file_name in os.listdir(output_folder):
            if is_video_file(file_name):
                try:
                    output_file_date = extract_date_from_filename(file_name)
                    if output_file_date:
                        video_date = datetime.strptime(output_file_date, "%Y%m%d")
                        if video_date < weeks_ago:
                            video_path = os.path.join(output_folder, file_name)
                            os.remove(video_path)
                            logging.info(f"已删除旧视频: {video_path}")
                except ValueError:
                    logging.warning(f"Invalid date format in file name: {file_name}")

    # 收集需要合并的小视频列表，按开始时间分到上午/下午。
    for file_name in os.listdir(input_folder):
        if is_video_file(file_name):  # 检查文件扩展名
            date_key = extract_date_from_filename(file_name)
            start_time = extract_start_time_from_filename(file_name)
            if date_key and start_time:
                current_file_date = datetime.strptime(date_key, "%Y%m%d")
                today_date = datetime.now().date()
                if current_file_date.date() == today_date:
                    logging.info(f"跳过当天录像: {file_name}")
                    continue
                half_day = extract_half_day_from_start_time(start_time)
                output_key = f"{date_key}-{half_day}"
                if output_key not in exist_videos_dict:
                    video_path = os.path.join(input_folder, file_name)
                    if output_key in videos_dict:
                        videos_dict[output_key].append(video_path)
                    else:
                        videos_dict[output_key] = [video_path]
                else:
                    continue
            elif date_key:
                logging.warning(f"Skipping video without 14-digit start time: {file_name}")

    if not videos_dict:
        logging.info("没有需要合并的新日期。")
        return

    logging.info(f"发现 {len(videos_dict)} 个待合并时间段: {', '.join(sorted(videos_dict))}")

    # 对每个日期的视频列表按时间戳排序
    for key, video_paths in videos_dict.items():
        # 提取文件名中的开始时间戳并排序
        valid_video_paths = []
        for video_path in video_paths:
            if extract_start_time_from_filename(os.path.basename(video_path)):
                valid_video_paths.append(video_path)
            else:
                logging.warning(f"Skipping video without 14-digit start time: {video_path}")
        sorted_video_paths = sorted(valid_video_paths, key=lambda x: extract_start_time_from_filename(os.path.basename(x)))
        videos_dict[key] = sorted_video_paths
        logging.info(f"{key}: 待合并 {len(sorted_video_paths)} 个片段。")

    # 合并视频
    for key in sorted(videos_dict):
        video_paths = videos_dict[key]
        if not video_paths:
            logging.warning(f"No valid videos found for date {key}, skipping merge.")
            continue
        logging.info(f"开始处理 {key}。")
        output_path = os.path.join(output_folder, f"{key}.mp4")
        tmp_file = None
        tmp_output_path = None
        try:
            # 创建一个临时文件列表
            tmp_file = create_concat_file(video_paths, output_folder, f"tmp_{key}_")
            tmp_output_path = create_temp_mp4(output_folder, f"tmp_{key}_")

            # 使用ffmpeg合并视频
            cmd = [*FFMPEG_BASE_CMD, "-f", "concat", "-safe", "0", "-i", tmp_file, "-c", "copy", tmp_output_path]
            subprocess.run(cmd, check=True)

            if compress:
                ensure_max_size(tmp_output_path, max_bytes=MAX_BYTES_5G)
            else:
                merged_size = os.path.getsize(tmp_output_path)
                logging.info(f"仅合并模式，跳过压缩检查。合并结果大小: {merged_size/(1024**3):.2f} GB。")
            os.replace(tmp_output_path, output_path)
            tmp_output_path = None
            final_size = os.path.getsize(output_path)
            logging.info(f"{key} 处理完成: {output_path} ({final_size/(1024**3):.2f} GB)")
        finally:
            cleanup_file(tmp_file)
            cleanup_file(tmp_output_path)

    logging.info("视频合并流程完成。")

def main():
    parser = argparse.ArgumentParser(description="Merge videos with the same prefix using ffmpeg.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--input", type=str, help="Input folder path containing videos", required=True)
    parser.add_argument("--output", type=str, help="Output folder path for merged videos", required=True)
    parser.add_argument("--compress", action="store_true", help="Compress merged videos when they exceed 5GB (default: False)")
    parser.add_argument("--delete-old-videos", action="store_true", help="Delete output videos older than one week (default: False)")
    args = parser.parse_args()
    logging.info("start merging videos.")
    merge_videos(args.input, args.output, args.delete_old_videos, args.compress)

if __name__ == "__main__":
    main()
