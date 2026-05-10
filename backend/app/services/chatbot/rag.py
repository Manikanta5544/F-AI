"""
RAG Chatbot service — Tasks #8 and #9.

Task #8 (Simple): Direct LLM completion via LangChain + FastAPI SSE.
Task #9 (RAG):    Retrieve from pgvector → inject context → stream answer.

Architecture:
  User query → [if RAG] cosine similarity retrieval from pgvector
             → build prompt with context sources
             → stream LLM response token-by-token via SSE
             → persist assistant message to DB
"""
from __future__ import annotations

from typing import AsyncIterator

from app.core.config import settings
from app.models.schemas.schemas import ChatSource


# ── Embedding ─────────────────────────────────────────────────────────────────
async def get_embedding_async(text: str) -> list[float]:
    """Async embedding via OpenAI text-embedding-3-small."""
    try:
        from openai import AsyncOpenAI  # type: ignore[import]
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.embeddings.create(
            input=text[:8000],
            model=settings.EMBEDDING_MODEL,
        )
        return response.data[0].embedding
    except Exception:
        # Zero vector fallback — works in CI / no-API-key mode
        return [0.0] * settings.EMBEDDING_DIMS


# ── Text chunking ─────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
    """
    Sliding window chunking with word-boundary respect.
    chunk_size / overlap are in approximate tokens (chars / 4 ≈ tokens).
    """
    char_size = chunk_size * 4
    char_overlap = overlap * 4
    chunks = []
    start = 0
    while start < len(text):
        end = start + char_size
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunks.append(text[start:end].strip())
        start = end - char_overlap
        if start >= len(text):
            break
    return [c for c in chunks if len(c) > 20]


# ── Document indexing ─────────────────────────────────────────────────────────
async def index_document(
    db,
    document_id: str,
    text: str,
    filename: str,
) -> int:
    """
    Chunk text, generate embeddings, store in document_chunks.
    Returns number of chunks indexed.
    Clears existing chunks first (idempotent re-indexing).
    """
    from sqlalchemy import delete
    from app.models.db.models import DocumentChunk

    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    chunks = chunk_text(text, settings.RAG_CHUNK_SIZE, settings.RAG_CHUNK_OVERLAP)
    for idx, chunk_content in enumerate(chunks):
        embedding = await get_embedding_async(chunk_content)
        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=idx,
            text=chunk_content,
            embedding=embedding,
            chunk_metadata={"filename": filename, "chunk_index": idx},
        )
        db.add(chunk)

    await db.flush()
    return len(chunks)


# ── pgvector retrieval ────────────────────────────────────────────────────────
async def retrieve_chunks(
    db,
    query: str,
    document_ids: list[str],
    top_k: int = 5,
) -> list[ChatSource]:
    """
    Cosine similarity retrieval via pgvector's <=> operator.
    Filters to specified document IDs, returns top_k chunks above 0.5 similarity.
    """
    from sqlalchemy import text as sql_text

    if not document_ids:
        return []

    query_embedding = await get_embedding_async(query)
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    sql = sql_text("""
        SELECT
            dc.document_id,
            dc.text,
            dc.chunk_metadata,
            d.filename,
            1 - (dc.embedding <=> :embedding::vector) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.document_id = ANY(:doc_ids)
          AND dc.embedding IS NOT NULL
        ORDER BY dc.embedding <=> :embedding::vector
        LIMIT :top_k
    """)

    result = await db.execute(sql, {
        "embedding": embedding_str,
        "doc_ids":   document_ids,
        "top_k":     top_k,
    })
    rows = result.fetchall()

    return [
        ChatSource(
            document_id=row.document_id,
            filename=row.filename,
            page_number=row.chunk_metadata.get("page_number", 1),
            chunk_text=row.text[:400],
            similarity=float(row.similarity),
            bbox=None,
        )
        for row in rows
        if float(row.similarity) > 0.5
    ]


# ── Prompt builders ───────────────────────────────────────────────────────────
def build_rag_prompt(query: str, sources: list[ChatSource]) -> str:
    context_parts = [
        f"[Source {i + 1} — {src.filename}]\n{src.chunk_text}"
        for i, src in enumerate(sources)
    ]
    context = "\n\n".join(context_parts)
    return (
        "You are an AI assistant specialised in analysing financial documents.\n"
        "Answer the user's question based ONLY on the provided document context.\n"
        "If the answer is not in the context, say so clearly. Cite which source you used.\n\n"
        f"DOCUMENT CONTEXT:\n{context}\n\n"
        f"USER QUESTION: {query}\n\nANSWER:"
    )


def build_simple_prompt(query: str) -> str:
    """Task #8 — direct LLM completion without document context."""
    return (
        "You are an AI assistant specialised in financial documents and data analysis.\n"
        "Answer the following question concisely and accurately.\n\n"
        f"QUESTION: {query}\n\nANSWER:"
    )


# ── LLM streaming ─────────────────────────────────────────────────────────────
async def stream_response(
    query: str,
    rag_enabled: bool,
    sources: list[ChatSource],
) -> AsyncIterator[str]:
    """
    Stream LLM response token by token via OpenAI streaming API.
    Falls back to a demo message when no API key is configured.
    """
    try:
        from openai import AsyncOpenAI  # type: ignore[import]
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        prompt = (
            build_rag_prompt(query, sources)
            if rag_enabled and sources
            else build_simple_prompt(query)
        )

        stream = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            max_tokens=1000,
            temperature=0.3,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    except Exception:
        # Demo mode — no OpenAI API key / network unavailable
        demo = f"[Demo mode — OpenAI API key not configured]\n\nYou asked: {query}"
        for word in demo.split():
            yield word + " "