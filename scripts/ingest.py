import os
from pathlib import Path
import pdfplumber
import psycopg2
from openai import OpenAI

from app.config import DB_URL, OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

def get_conn():
    return psycopg2.connect(DB_URL)

def extract_pdf(pdf_path: Path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append((i + 1, text))
    return pages

def split_text(text: str, max_len: int = 500):
    # 很简单的切分，后面可以换成“按条款号切”
    chunks = []
    buf = ""
    for line in text.splitlines():
        if len(buf) + len(line) < max_len:
            buf += line + "\n"
        else:
            chunks.append(buf.strip())
            buf = line + "\n"
    if buf.strip():
        chunks.append(buf.strip())
    return chunks

def embed(text: str):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding

def insert_chunk(conn, content, emb, source, page, bucket):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (content, embedding, source, page, bucket)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (content, emb, source, page, bucket)
        )
    conn.commit()

def ingest_pdf(pdf_path: str, bucket: str):
    pdf_path = Path(pdf_path)
    assert pdf_path.exists(), f"PDF not found: {pdf_path}"
    conn = get_conn()
    pages = extract_pdf(pdf_path)
    source = pdf_path.name
    for page_num, text in pages:
        chunks = split_text(text, max_len=500)
        for c in chunks:
            if not c.strip():
                continue
            emb = embed(c)
            insert_chunk(conn, c, emb, source, page_num, bucket)
            print(f"inserted: {source} p{page_num}")
    conn.close()

if __name__ == "__main__":
    # PDF 放到 data/ 下
    ingest_pdf("data/Sample.pdf", bucket="oncor")
    # ingest_pdf("data/ercot_protocol.pdf", bucket="ercot")
