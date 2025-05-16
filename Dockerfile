FROM python:3.8

RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*


COPY ./all_in_one_merger.py /app/all_in_one_merger.py


ENV PYTHONUNBUFFERED=1


CMD ["python", "all_in_one_merger.py", "--input", "/app/input", "--output", "/app/output"]
