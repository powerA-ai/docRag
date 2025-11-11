from dotenv import load_dotenv
from pathlib import Path
import os

# 先加载项目自己的 .env
# .env 设置 DB_URL
project_env = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=project_env)

# 再加载上层的全局 .env
# 上一层文件夹 .env 设置 OPENAI_API_KEY=sk-xxxxxx
global_env = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=global_env)

# 验证变量是否加载成功
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_URL = os.getenv("DB_URL")
print("API Key Loaded:", bool(OPENAI_API_KEY))
print("DB_URL Loaded:", bool(DB_URL))