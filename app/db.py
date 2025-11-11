from app.config import DB_URL
import psycopg2

def get_conn():
    """创建并返回数据库连接"""
    if not DB_URL:
        raise ValueError("❌ 未检测到 DB_URL，请检查 .env 文件配置")
    return psycopg2.connect(DB_URL)
