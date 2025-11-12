# app/main.py

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from pydantic import BaseModel
from app.db import get_conn
from app.config import DB_URL
from app.rag import answer_question

app = FastAPI()

# 挂载静态目录
static_dir = Path(__file__).resolve().parents[1] / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/ui")
def ui():
    return FileResponse(static_dir / "index.html")

@app.get("/")
def read_root():
    return {"msg": "hello rag"}

@app.get("/dbtest")
def dbtest():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        conn.close()
        return {
            "ok": True,
            "postgres_version": version,
            "DB_URL": DB_URL,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "DB_URL": DB_URL,
        }

class AskRequest(BaseModel):
    query: str
    bucket: str | None = None   # "oncor" / "ercot" / None

@app.post("/ask")
def ask(req: AskRequest):
    answer, sources = answer_question(req.query, bucket=req.bucket)
    return {
        "answer": answer,
        "sources": sources
    }
