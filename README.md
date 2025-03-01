# xiaomi-camera-merge-tool
新款小米摄像头录像文件合并工具，将十几分钟一个的小视频合并为以天为一个视频进行保存按天保存

# 必要软件
需要提前准备好ffmpeg

## 用法
将十几分钟一个视频合并为以小时为一个视频进行保存按天保存，**（注意⚠️：每次调用该脚本不会重复产生相同的文件，只会增量更新）**

```python merge_daily_ffmepg.py --input <小米摄像头录像文件夹绝对路径> --output <保存视频的绝对路径> ```

举例：

例如我的录像文件存储在e盘下的/movie/xiaomi_camera_videos/78DF72DE6C4E， 我想把合并好的视频文件存储在e盘下的/movie/daily，那么命令如下：

``` python merge_daily_ffmepg.py --input /e/movie/xiaomi_camera_videos/78DF72DE6C4E --output /e/movie/daily/ ```

目前新款小米摄像头的文件结构基本都是下图这样子，例如我在米家app里面指定了nas（或者win的共享存储）存储路径为E盘下的movie文件夹，那么小米摄像头会在movie文件夹下创建一个xiaomi_camera_videos目录，然后再下面就是以摄像头UUID命名的目录，最下面就是一个一个的视频文件
![小米摄像头文件结构](https://github.com/Mrhs121/xiaomi-camera-merge-tool/blob/main/Snipaste_2025-03-01_20-24-22.png)

合并后，将十几分钟一个的小视频合并为以天为一个视频进行保存按天保存（我是小米智能摄像头3pro，3k分辨率，每天的视频大小大约9个G）
![合并后的文件结构](https://github.com/Mrhs121/xiaomi-camera-merge-tool/blob/main/Snipaste_2025-03-01_20-25-31.png)
