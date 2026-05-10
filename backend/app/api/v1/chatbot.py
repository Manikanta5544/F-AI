"""
Chatbot API routes — Task #8 (simple LangChain) and Task #9 (RAG).

"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.db.models import ChatMessage, ChatSession, User
from app.models.schemas.schemas import (
    ApiResponse, ChatSessionOut,
    CreateSessionRequest,
)

router = APIRouter(prefix="/chat", tags=["chatbot"])


@router.get("/sessions", response_model=ApiResponse)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.created_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    return ApiResponse(data=[ChatSessionOut.model_validate(s) for s in sessions])


@router.post("/sessions", response_model=ApiResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = ChatSession(
        user_id=current_user.id,
        rag_enabled=body.rag_enabled,
        document_ids=body.document_ids,
        title="New chat",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return ApiResponse(data=ChatSessionOut.model_validate(session))


@router.get("/sessions/{session_id}", response_model=ApiResponse)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ApiResponse(data=ChatSessionOut.model_validate(session))


@router.get("/sessions/{session_id}/stream")
async def stream_chat(
    session_id: str,
    message: str = Query(..., min_length=1, max_length=8000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    SSE streaming chat — Tasks #8 and #9.

    Task #8 (rag_enabled=False): direct LLM completion.
    Task #9 (rag_enabled=True):  pgvector retrieval → context injection → stream.

    Protocol:
      event: sources  → JSON array of ChatSource (RAG only, before streaming starts)
      event: token    → single token string
      event: done     → empty, stream finished
      event: error    → { message: str }
    """
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Persist user message before streaming starts (avoids session expiry issues)
    user_msg = ChatMessage(session_id=session_id, role="user", content=message)
    db.add(user_msg)

    # Update session title from first user message
    if session.title == "New chat":
        session.title = message[:60] + ("…" if len(message) > 60 else "")

    await db.flush()
    await db.commit()   # commit before entering the streaming generator

    async def event_stream():
        from app.services.chatbot.rag import retrieve_chunks, stream_response
        from app.core.database import AsyncSessionFactory

        # FIX: Use a fresh session inside the generator — the request session
        # may expire during long SSE streams. This is the correct pattern.
        async with AsyncSessionFactory() as stream_db:
            sources = []
            if session.rag_enabled and session.document_ids:
                try:
                    sources = await retrieve_chunks(stream_db, message, session.document_ids)
                except Exception:
                    sources = []

            if sources:
                yield f"event: sources\ndata: {json.dumps([s.model_dump() for s in sources])}\n\n"

            accumulated = ""
            try:
                async for token in stream_response(message, session.rag_enabled, sources):
                    accumulated += token
                    yield f"event: token\ndata: {token}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                return

            # Persist assistant message
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=accumulated,
                sources=[s.model_dump() for s in sources],
            )
            stream_db.add(assistant_msg)
            await stream_db.flush()
            await stream_db.commit()

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(session)