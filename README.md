# xiaomi-camera-merge-tool
新款小米摄像头录像文件合并工具，将十几分钟一个的小视频合并为以天为一个视频进行保存按天保存

oldmi_merge_daily_ffmepg.py ：适用于以下存储格式的老款摄像头，如下：
<img width="307" alt="截屏2025-04-11 01 09 20" src="https://github.com/user-attachments/assets/c15b10bc-2622-4d4c-bac9-b13768feeafe" />

merge_daily_ffmepg.py ：适用于以下存储格式的新款摄像头，如下：
![小米摄像头文件结构](https://github.com/Mrhs121/xiaomi-camera-merge-tool/blob/main/Snipaste_2025-03-01_20-24-22.png)


# 必要软件
非docker环境需要提前准备好ffmpeg以及python

## 原生脚本用法
将十几分钟一个视频合并为以小时为一个视频进行保存按天保存，**（注意⚠️：每次调用该脚本不会重复产生相同的文件，只会增量更新）**

```python merge_daily_ffmepg.py --input <小米摄像头录像文件夹绝对路径> --output <保存视频的绝对路径> ```

举例：

例如我的录像文件存储在e盘下的/movie/xiaomi_camera_videos/78DF72DE6C4E， 我想把合并好的视频文件存储在e盘下的/movie/daily，那么命令如下：

``` python merge_daily_ffmepg.py --input /e/movie/xiaomi_camera_videos/78DF72DE6C4E --output /e/movie/daily/ ```

目前新款小米摄像头的文件结构基本都是下图这样子，例如我在米家app里面指定了nas（或者win的共享存储）存储路径为E盘下的movie文件夹，那么小米摄像头会在movie文件夹下创建一个xiaomi_camera_videos目录，然后再下面就是以摄像头UUID命名的目录，最下面就是一个一个的视频文件
![小米摄像头文件结构](https://github.com/Mrhs121/xiaomi-camera-merge-tool/blob/main/Snipaste_2025-03-01_20-24-22.png)

合并后，将十几分钟一个的小视频合并为以天为一个视频进行保存按天保存（我是小米智能摄像头3pro，3k分辨率，每天的视频大小大约9个G）
![合并后的文件结构](https://github.com/Mrhs121/xiaomi-camera-merge-tool/blob/main/Snipaste_2025-03-01_20-25-31.png)

# Docker

## 3.0
**该镜像集成了新款和老款摄像头的支持**

``` docker pull shengsheng123/xiaomi-camera-merge-tool-x86:3.0 ```
### 新款摄像头：
默认为新款，无需填写额外的参数 \
可选参数：```--delete-old-videos```，默认为 false ，指定后会删除 output 问价价中一周前的旧文件

**推荐如下使用姿势的同学开启此参数：**
output路径为ssd盘上的一个临时文件夹，每天定时任务再冷备份到hdd盘，这样就可以在合并的时候把ssd临时文件夹中的老文件删除了

#### NAS开启此参数(飞牛举例)
<img width="683" alt="截屏2025-04-06 21 42 16" src="https://github.com/user-attachments/assets/464b3497-aa22-4ebf-84e0-592b6136062a" />

### 老款摄像头：
需要在命令中填写 ```--old-cam``` 参数
#### NAS开启此参数(飞牛举例)

## 2.0
``` docker pull shengsheng123/xiaomi-camera-merge-tool-x86:2.0 ```

镜像新增参数 --delete-old-videos，默认为false，指定后会删除output中一周前的旧文件

**推荐如下使用姿势的同学开启此参数：**
output路径为ssd盘上的一个临时文件夹，每天定时任务再冷备份到hdd盘，这样就可以在合并的时候把ssd临时文件夹中的老文件删除了
#### NAS开启此参数(飞牛举例)
<img width="683" alt="截屏2025-04-06 21 42 16" src="https://github.com/user-attachments/assets/464b3497-aa22-4ebf-84e0-592b6136062a" />




## 1.0
**目前docker镜像只适配了新款摄像头的存储格式**
https://hub.docker.com/repository/docker/shengsheng123/xiaomi-camera-merge-tool-x86/general

```docker pull shengsheng123/xiaomi-camera-merge-tool-x86:1.0```
## NAS(飞牛举例)
飞牛社区博客：https://club.fnnas.com/forum.php?mod=viewthread&tid=17854

将录像文件的存储路径映射到容器的 /app/input, 将合并后的视频保存路径映射到容器的 /app/output

![飞牛](https://github.com/Mrhs121/xiaomi-camera-merge-tool/blob/main/%E6%88%AA%E5%B1%8F2025-03-08%2013.15.05.png)



