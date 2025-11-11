# app/main.py
from app.db import get_conn
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"msg": "hello rag"}

@app.get("/dbtest")
def dbtest():
    """测试 PostgreSQL 是否连接成功"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()
    conn.close()
    return {"postgres_version": version}