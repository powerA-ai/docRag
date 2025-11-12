# app/main.py

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import List, Literal, Optional
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

class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class AskRequest(BaseModel):
    query: str
    bucket: Optional[str] = None  # "oncor" / "ercot" / None
    top_k: int = 6
    history: List[HistoryTurn] = []
    max_distance: Optional[float] = None   # 允许前端调阈值

@app.post("/ask")
def ask(req: AskRequest):
    answer, sources = answer_question(
        req.query,
        bucket=req.bucket,
        topk=req.top_k,
        history=[h.model_dump() for h in req.history],  # 传递给 RAG
        max_distance=req.max_distance,
    )
    return {"answer": answer, "sources": sources}
