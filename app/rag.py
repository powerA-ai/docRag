# app/rag.py
import psycopg2
from openai import OpenAI
from app.config import DB_URL, OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def embed_query(text: str):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding


def _to_pgvector(vec: list[float]) -> str:
    # pgvector 的文本格式是 [0.1,0.2,0.3]
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def search_docs(query: str, bucket: str | None = None, topk: int = 6, max_distance: float = 0.4):
    # 生成查询向量
    q_emb = embed_query(query)
    q_vec_literal = _to_pgvector(q_emb)  # 变成 "[0.123,0.456,...]" 这种

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    if bucket:
        sql = f"""
            SELECT content,
                   source,
                   section,
                   title,
                   page,
                   (embedding <-> '{q_vec_literal}'::vector) AS distance
            FROM documents
            WHERE bucket = %s
            ORDER BY distance
            LIMIT %s;
        """
        cur.execute(sql, (bucket, topk))
    else:
        sql = f"""
            SELECT content,
                   source,
                   section,
                   title,
                   page,
                   (embedding <-> '{q_vec_literal}'::vector) AS distance
            FROM documents
            ORDER BY distance
            LIMIT %s;
        """
        cur.execute(sql, (topk,))

    rows = cur.fetchall()
    conn.close()

    results = []
    for content, source, section, title, page, distance in rows:
        # 相似度阈值过滤
        if distance is not None and distance <= max_distance:
            results.append({
                "content": content,
                "source": source,
                "section": section,
                "title": title,
                "page": page,
                "distance": float(distance),
            })
    return results

def is_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def build_context(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        meta = f"[source: {c['source']}, section: {c['section']}, page: {c['page']}]"
        parts.append(meta + "\n" + c["content"])
    return "\n\n".join(parts)


BASE_PROMPT = """You are an assistant specialized in ERCOT and Texas TDSP (e.g. Oncor) tariffs and technical documents.
Answer ONLY using the provided context. If the answer is not in the context, say clearly that it is not found.
Always cite the document name and section/page if available.
If the user asks for an explanation for business/client, give a short plain-language explanation first, then a technical note.

Context:
{context}

User question:
{question}

Answer:
"""


def answer_question(query: str, bucket: str | None = None, topk: int = 6, history: list[dict] | None = None):
    chunks = search_docs(query, bucket=bucket, topk=topk)
    if not chunks:
        if is_chinese(query):
            ans = "未找到相关内容，请确认文档是否已导入或换个说法再试。"
        else:
            ans = "No relevant content found. Please check if the document is loaded or try rephrasing your question."
        return ans, []

    context = build_context(chunks)

    # 只取最近 6 轮历史，避免提示太长
    history = history or []
    recent = history[-6:]

    # 把历史拼成一段可读文本
    hist_text = "\n".join(
        (("User: " if h["role"]=="user" else "Assistant: ") + h["content"].strip())
        for h in recent
    )

    # 语言设置
    prompt = BASE_PROMPT
    if is_chinese(query):
        prompt += "\nAnswer in Chinese. Keep section numbers and document names in English.\n"

    # 合成最终提示：历史 + 上下文 + 当前问题
    if hist_text:
        prompt = (
            "Conversation so far:\n"
            f"{hist_text}\n\n"
        ) + prompt

    prompt = prompt.format(context=context, question=query)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    answer = resp.choices[0].message.content

    formatted_sources = [
        {
            "doc": c["source"],
            "page": c["page"],
            "section": c["section"],
            "snippet": (c["content"][:200] + "…") if len(c["content"]) > 200 else c["content"]
        }
        for c in chunks
    ]

    return answer, formatted_sources

