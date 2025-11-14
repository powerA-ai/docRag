# docRAG — A Lightweight RAG System for Energy Industry Documentation
Retrieval-Augmented Generation for ERCOT / Oncor Tariffs / Protocols

---

## Overview

**docRAG** is a lightweight, production-oriented **Retrieval-Augmented Generation (RAG)** system designed to parse, index, and query complex energy-sector documentation, including:

- ERCOT Nodal Protocols  
- Oncor / CenterPoint tariffs  
- Interconnection requirements  
- Engineering specifications and standards  
- Contracts and regulatory filings  

The system provides:

- PDF parsing with TOC and section-number extraction  
- Automatic structure-aware chunking (e.g. `Section 3.3.1`, `3.3.2.1`)  
- Soft chunking for long sections  
- Embedding with OpenAI `text-embedding-3-small`  
- Vector search with PostgreSQL + pgvector  
- FastAPI backend with a built-in web UI  
- Multilingual (English + Chinese) question answering  
- Query logs stored in PostgreSQL  
- Duplicate-free ingestion via content hashing + UPSERT  

---

## Architecture & Core Algorithms

### 1. Document Chunking

docRAG uses a **two-layer hybrid chunking strategy** suited for regulatory and technical documents.

#### Layer 1: Structural Chunking

For each PDF:

1. Extract the Table of Contents (TOC) when available  
2. If TOC is missing, detect headings via regex:

```bash
Section 3.3.1
3.3.1 ERCOT Approval of New or Relocated Facilities
6.1.1.1.5 Distribution System Charge
```


Each heading becomes a section with:

- `section`  
- `title`  
- `page_start`, `page_end`  
- combined text from the page range  

#### Layer 2: Soft Chunking

To avoid embeddings on excessive long text:

- Target length: **1200–2000 characters**  
- Overlap: **≈200 characters**  
- Prefer splitting at newlines or punctuation  
- Always move forward (no infinite backtracking)  

This yields clean semantic chunks for embedding.

---

### 2. Embeddings & PostgreSQL Storage

Chunks are embedded using: `OpenAI text-embedding-3-small`

Stored in PostgreSQL via pgvector:

- Column: `embedding vector(1536)`
- Similarity: `embedding <-> query_embedding`
- Index: `ivfflat` (cosine distance)

Deduplication uses:

- `content_hash = md5(content)`
- UNIQUE index on `(source, bucket, section, page_start, page_end, content_hash)`
- Insert via UPSERT:

```sql
INSERT ... ON CONFLICT DO NOTHING
```

### 3. RAG Retrieval

The retrieval workflow operates as follows:

1. **Embed the user query** using `text-embedding-3-small`.
2. **Search the PostgreSQL pgvector index** using cosine similarity: `ORDER BY embedding <-> query_embedding`

3. **Deduplicate results** by `(source, section, page_start, page_end)`  
to avoid repeated citations from overlapping chunks.
4. **Build an LLM prompt** including:
- The user question
- Retrieved context snippets
- Metadata (document name, section number, page range)
5. **Generate the final answer** in English or Chinese depending on the user query.
6. **Store the query & answer** in the `query_logs` table for auditability and metrics.

---

## Features

### Document Ingestion (PDF → Vector DB)

Run:

```bash
python -m scripts.ingest
```

## Ingestion performs

- PDF parsing  
- TOC/regex-based structural chunking  
- Soft chunking for long text  
- Generating embeddings via OpenAI  
- Duplicate-free insertion using UPSERT  
- Logging inserted sections and chunks  

---

## FastAPI Endpoints

| Endpoint       | Method | Description |
|----------------|--------|-------------|
| `/ask`         | POST   | RAG question answering |
| `/logs`        | GET    | List recent query logs |
| `/logs/{id}`   | GET    | View a specific log entry |
| `/logs/export` | GET    | Export logs in CSV format |

Example request:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "How does ERCOT approve new Transmission Facilities?", "bucket": "ercot"}'
```

## Web UI

Open in browser:

http://localhost:8000/ui


Features:

- Multi-turn conversational interface  
- Displays answer + sources for each question  
- “Clear history” button resets UI state  
- Supports English and Chinese questions  
- Frontend served directly by FastAPI (`/app/static/index.html`)  

---

## Project Structure
```powershell
docRag/
├── app/
│   ├── main.py          # FastAPI entrypoint
│   ├── rag.py           # RAG search + LLM generation
│   ├── config.py        # Environment variable loader
│   └── static/
│       └── index.html   # Frontend UI
│
├── scripts/
│   └── ingest.py        # PDF → chunks → embeddings → DB
│
├── data/
│   └── Sample.pdf
│
└── README.md
```






