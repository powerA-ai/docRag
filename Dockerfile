FROM python:3.12-slim

# 安装系统依赖（psycopg2 需要）
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制 requirements.txt 并安装依赖（利用 Docker 缓存）
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 再复制代码
COPY app /app/app
COPY scripts /app/scripts
COPY data /app/data

# FastAPI 运行所需的环境变量在 docker-compose 里传
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
