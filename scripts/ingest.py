# scripts/ingest.py
import os
import re
import psycopg2
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import hashlib
from openai import OpenAI

from app.config import DB_URL, OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# ------------ 嵌入 ------------
def embed(text: str) -> List[float]:
    text = text.strip()
    if not text:
        return []
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding

# ------------ 切分：标题/条款号 ------------
SEC_PATTERNS = [
    # "Section 3.3.1  Title"
    re.compile(r'(?i)^\s*(section)\s+(\d+(?:\.\d+)+)\s*[:\-–]?\s*(.*\S)?\s*$'),
    # "3.3.1  Title"
    re.compile(r'^\s*(\d+(?:\.\d+){1,6})\s+([A-Z][^\n]{0,120})?\s*$'),
    # Oncor 常见条款："6.1.1.1.5 Distribution System Charge (DSC)"
    re.compile(r'^\s*(\d+(?:\.\d+){2,7})\s+([A-Za-z][^\n]{0,160})\s*$'),
]

def detect_heading(line: str) -> Optional[Tuple[str, str]]:
    """匹配返回 (section_label, title)。匹配失败返回 None。"""
    for pat in SEC_PATTERNS:
        m = pat.match(line)
        if not m:
            continue
        groups = [g for g in m.groups() if g is not None]
        # 根据不同正则形态回组
        if len(groups) == 3 and groups[0].lower() == "section":
            # e.g. "Section 3.3.1 Title"
            return (groups[1], groups[2] or "")
        elif len(groups) == 2:
            # e.g. "3.3.1 Title"
            return (groups[0], groups[1] or "")
    return None

def extract_sections_with_toc(pdf_path: str):
    """优先用 TOC（目录），回退到正则扫描，返回 list[dict]：
       dict: {section, title, page_start, page_end, text}
    """
    doc = fitz.open(pdf_path)
    print(f"[INGEST] open PDF: {pdf_path} ({doc.page_count} pages)")

    # 1) 先尝试 TOC（很多规范/协议类 PDF 有目录）
    toc = doc.get_toc(simple=True)  # [(level, title, page_no), ...] page从1起
    sections = []
    if toc:
        print(f"[INGEST] TOC entries: {len(toc)} (using TOC to cut)")
        # 只取 level 2/3 标题更准；没要求就都用
        for i, (lvl, title, page1) in enumerate(toc):
            page_start = max(1, int(page1))
            page_end = int(toc[i+1][2] - 1) if i+1 < len(toc) else doc.page_count
            # 抽取文本
            text_parts = []
            for p in range(page_start-1, page_end):
                text_parts.append(doc.load_page(p).get_text("text"))
            block_text = "\n".join(text_parts).strip()

            # 尝试从 title 中抽 section 号
            sec = None
            m = re.search(r'(?i)(?:section\s+)?(\d+(?:\.\d+)+)', title)
            if m:
                sec = m.group(1)
            sections.append({
                "section": sec,
                "title": title.strip(),
                "page_start": page_start,
                "page_end": page_end,
                "text": block_text
            })

    # 2) 如果没有 TOC，回退到逐页正则识别标题
    if not sections:
        print("[INGEST] No TOC/regex headings detected; fallback to whole document")
        headings = []  # [(page_idx0, section_label, title, y_order, line_text)]
        for p in range(doc.page_count):
            page = doc.load_page(p)
            page_text = page.get_text("text")
            for raw_line in page_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                h = detect_heading(line)
                if h:
                    headings.append((p, h[0], h[1], line))

        # 用识别到的 heading 将全文切块
        if headings:
            # 根据出现顺序切分
            for i, (p0, sec, title, _) in enumerate(headings):
                page_start = p0 + 1
                page_end = (headings[i+1][0] + 1) - 1 if i+1 < len(headings) else doc.page_count
                text_parts = []
                for p in range(page_start-1, page_end):
                    text_parts.append(doc.load_page(p).get_text("text"))
                block_text = "\n".join(text_parts).strip()
                sections.append({
                    "section": sec,
                    "title": title.strip(),
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": block_text
                })

    # 3) 若还是识别不到，退化为整页拼段（保证可用）
    if not sections:
        print("[INGEST] Still cannot detect headings; fallback to paragraphing whole document")
        text_parts = []
        for p in range(doc.page_count):
            text_parts.append(doc.load_page(p).get_text("text"))
        whole = "\n".join(text_parts).strip()
        sections = [{
            "section": None,
            "title": Path(pdf_path).name,
            "page_start": 1,
            "page_end": doc.page_count,
            "text": whole
        }]

    doc.close()
    print(f"[INGEST] sections detected: {len(sections)}")
    return sections

# ------------ 二级切分（防止块过大） ------------
def soft_chunk(text: str, max_chars=2000, overlap=200) -> list[str]:
    """
    把很长的段落再软切，尽量在换行/句号处分割，保留 overlap。
    关键修复：
    - 真的向前推进（即便找不到断点也会用 end 强制推进）
    - overlap 只在 cut > start 时生效，保证不倒退
    """
    text = text.strip()
    n = len(text)
    if n <= max_chars:
        return [text] if n else []

    chunks = []
    start = 0
    while start < n:
        end = min(n, start + max_chars)

        # 优先在窗口内找“较舒服”的断点（换行、句号）
        cut = text.rfind("\n", start + 1, end)  # 避免 cut == start 导致不前进
        if cut == -1:
            cut = text.rfind(".", start + 1, end)
        if cut == -1 or cut <= start:
            cut = end  # 强制推进

        segment = text[start:cut].strip()
        if segment:
            chunks.append(segment)

        # 计算下一轮起点：尽量保留 overlap，但必须前进
        next_start = cut - overlap
        if next_start <= start:
            next_start = cut  # 确保前进
        start = next_start

    return chunks

# ------------ 写库 ------------
def ensure_table():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    print("[INGEST] ensure documents table exists...")

    # 1) 创建表（如果不存在）
    cur.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        content  TEXT NOT NULL,
        embedding vector(1536),
        source   TEXT,
        section  TEXT,
        title    TEXT,
        page     INT,
        page_start INT,
        page_end   INT,
        bucket   TEXT,
        content_hash TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)

    # 2) 给 content_hash 填已有旧数据
    cur.execute("""
        UPDATE documents
        SET content_hash = md5(content)
        WHERE content_hash IS NULL;
    """)

    # 3) 创建 UPSERT 所需的唯一索引
    #   注意：只有当前用户是 owner 才能成功创建
    cur.execute("""
    DO $$
    DECLARE
        owner text;
    BEGIN
        -- 查 documents 的所有人
        SELECT pg_get_userbyid(relowner)
        INTO owner
        FROM pg_class
        WHERE relname='documents'
          AND relnamespace='public'::regnamespace;

        IF owner = current_user THEN
            -- 如果索引不存在，则创建
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname='public'
                  AND indexname='uniq_doc_block'
            ) THEN
                RAISE NOTICE 'creating unique index uniq_doc_block...';
                CREATE UNIQUE INDEX uniq_doc_block
                ON public.documents (
                    source,
                    bucket,
                    COALESCE(section,''),
                    page_start,
                    page_end,
                    content_hash
                );
            END IF;
        ELSE
            RAISE NOTICE 'skip index creation because current_user % is NOT owner %', current_user, owner;
        END IF;
    END$$;
    """)

    conn.commit()
    conn.close()


def insert_record(conn, content, emb, source, section, title,
                  page_start, page_end, bucket):
    cur = conn.cursor()

    # 计算内容哈希
    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

    cur.execute("""
        INSERT INTO documents (
            content,
            embedding,
            source,
            section,
            title,
            page,
            page_start,
            page_end,
            bucket,
            content_hash
        )
        VALUES (
            %s,
            %s::vector,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (source, bucket, COALESCE(section,''), page_start, page_end, content_hash)
        DO NOTHING;
    """, (
        content,
        "[" + ",".join(f"{x:.6f}" for x in emb) + "]",
        source,
        section,
        title,
        page_start,   # 保持page = page_start 兼容旧逻辑
        page_start,
        page_end,
        bucket,
        content_hash
    ))

    conn.commit()


def ingest_pdf(pdf_path: str, bucket: str):
    ensure_table()
    pdf_path = str(pdf_path)
    sections = extract_sections_with_toc(pdf_path)
    conn = psycopg2.connect(DB_URL)
    src_name = Path(pdf_path).name

    print(f"[INGEST] start ingest: {src_name} | sections={len(sections)} | bucket={bucket}")

    inserted = 0
    for si, sec in enumerate(sections, start=1):
        sec_label = sec["section"]
        title = sec["title"]
        page_start = sec["page_start"]
        page_end = sec["page_end"]
        text = sec["text"]

        print(f"[INGEST] section {si}/{len(sections)}: sec={sec_label or '-'} | "
              f"title='{title[:60]}' | pages {page_start}-{page_end} | len={len(text)}")

        sub_chunks = soft_chunk(text, max_chars=2000, overlap=200)
        print(f"[INGEST]   -> soft-chunks: {len(sub_chunks)}")

        for ci, sub in enumerate(sub_chunks, start=1):
            decorated = f"[{src_name} | sec:{sec_label or '-'} | {title} | p.{page_start}-{page_end}]\n{sub}"
            emb = embed(decorated)
            if not emb:
                print(f"[INGEST][WARN] empty embedding at section {si} chunk {ci}, skip")
                continue

            insert_record(
                conn,
                decorated,
                emb,
                src_name,
                sec_label,
                title,
                page_start,
                page_end,
                bucket
            )
            inserted += 1
            if ci % 10 == 0:
                print(f"[INGEST]   -> inserted {inserted} chunks total...")

    conn.close()
    print(f"✅ Ingest OK: {src_name} | total chunks inserted = {inserted}")


# ------------ CLI ------------
if __name__ == "__main__":
    # 示例：可以按需替换为实际文件
    # ingest_pdf("data/Tariff-for-Retail-Delivery-Service.pdf", bucket="oncor")
    # ingest_pdf("data/September-1-2025-Nodal-Protocols.pdf", bucket="ercot")
    ingest_pdf("data/Sample.pdf", bucket="ercot")
