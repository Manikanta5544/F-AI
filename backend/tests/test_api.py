"""
Integration tests covering all 11 tasks via HTTP.
Uses in-memory SQLite + monkeypatched Celery/MinIO.
"""
from __future__ import annotations

import io

import pytest
from httpx import AsyncClient

from app.models.db.models import User


# ── Helpers ───────────────────────────────────────────────────────────────────
def _mock_task():
    return type("Task", (), {"id": "mock-celery-id"})()


def _make_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n9\n%%EOF"
    )


async def _mock_upload(file_bytes, filename, bucket=None):
    return "uploads/2024/01/01/abc123.pdf", "a" * 64


# ── Health ────────────────────────────────────────────────────────────────────
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Auth ──────────────────────────────────────────────────────────────────────
class TestAuth:
    async def test_login_success(self, client, test_user):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "test@example.com", "password": "password123",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()["data"]

    async def test_login_wrong_password(self, client, test_user):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "test@example.com", "password": "wrong",
        })
        assert resp.status_code == 401

    async def test_login_unknown_email(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@x.com", "password": "password123",
        })
        assert resp.status_code == 401

    async def test_me_authenticated(self, client, auth_headers, test_user):
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == "test@example.com"

    async def test_me_unauthenticated(self, client):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_register(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "new@example.com", "password": "password123", "name": "New User",
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["email"] == "new@example.com"

    async def test_register_duplicate_email(self, client, test_user):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "test@example.com", "password": "password123", "name": "Dup",
        })
        assert resp.status_code == 400


# ── Task #4/#6/#7 — OCR ───────────────────────────────────────────────────────
class TestOCR:
    async def test_submit_ocr_success(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.ocr_tasks.run_ocr.apply_async", lambda *a, **kw: _mock_task())
        monkeypatch.setattr("app.api.v1.ocr.upload_file", _mock_upload)

        resp = await client.post(
            "/api/v1/ocr/submit", headers=auth_headers,
            files={"file": ("test.pdf", io.BytesIO(_make_pdf()), "application/pdf")},
            data={"mode": "fast"},
        )
        assert resp.status_code == 202
        data = resp.json()["data"]
        assert data["status"] == "pending"
        assert "id" in data

    async def test_submit_unsupported_type(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/ocr/submit", headers=auth_headers,
            files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        )
        assert resp.status_code == 415

    async def test_result_not_found(self, client, auth_headers):
        resp = await client.get("/api/v1/ocr/results/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    async def test_history_empty(self, client, auth_headers):
        resp = await client.get("/api/v1/ocr/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

    async def test_idempotency_same_file_same_mode(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.ocr_tasks.run_ocr.apply_async", lambda *a, **kw: _mock_task())
        fixed_hash = "b" * 64

        async def fixed_upload(fb, fn, bucket=None):
            return "uploads/fixed.pdf", fixed_hash

        monkeypatch.setattr("app.api.v1.ocr.upload_file", fixed_upload)
        pdf = _make_pdf()
        kwargs = dict(
            headers=auth_headers,
            files={"file": ("doc.pdf", io.BytesIO(pdf), "application/pdf")},
            data={"mode": "fast"},
        )
        r1 = await client.post("/api/v1/ocr/submit", **kwargs)
        kwargs["files"] = {"file": ("doc.pdf", io.BytesIO(pdf), "application/pdf")}
        r2 = await client.post("/api/v1/ocr/submit", **kwargs)
        assert r1.status_code == r2.status_code == 202
        assert r1.json()["data"]["id"] == r2.json()["data"]["id"]


# ── Tasks #1–3 — Scraper ──────────────────────────────────────────────────────
class TestScraper:
    async def test_submit_amazon(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.scraper_tasks.run_scrape.apply_async", lambda *a, **kw: _mock_task())
        resp = await client.post(
            "/api/v1/scraper/submit", headers=auth_headers,
            json={"platform": "amazon", "urls": ["https://amazon.in/dp/ABC123"]},
        )
        assert resp.status_code == 202

    async def test_submit_manual_brand(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.scraper_tasks.run_scrape.apply_async", lambda *a, **kw: _mock_task())
        resp = await client.post(
            "/api/v1/scraper/submit", headers=auth_headers,
            json={"platform": "manual", "urls": ["https://nykaa.com/p/123"], "brand_filter": ["nykaa"]},
        )
        assert resp.status_code == 202

    async def test_invalid_platform(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/scraper/submit", headers=auth_headers,
            json={"platform": "ebay", "urls": ["https://ebay.com/123"]},
        )
        assert resp.status_code == 422

    async def test_empty_urls_rejected(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/scraper/submit", headers=auth_headers,
            json={"platform": "amazon", "urls": []},
        )
        assert resp.status_code == 422


# ── Tasks #5, #11 — Extraction ────────────────────────────────────────────────
class TestExtraction:
    async def test_submit_bank_statement(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.extraction_tasks.run_extraction.apply_async", lambda *a, **kw: _mock_task())
        monkeypatch.setattr("app.api.v1.extraction.upload_file", _mock_upload)
        resp = await client.post(
            "/api/v1/extraction/bank-statement", headers=auth_headers,
            files={"file": ("bank.pdf", io.BytesIO(_make_pdf()), "application/pdf")},
        )
        assert resp.status_code == 202

    async def test_submit_invoice(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.extraction_tasks.run_extraction.apply_async", lambda *a, **kw: _mock_task())
        monkeypatch.setattr("app.api.v1.extraction.upload_file", _mock_upload)
        resp = await client.post(
            "/api/v1/extraction/invoice", headers=auth_headers,
            files={"file": ("inv.pdf", io.BytesIO(_make_pdf()), "application/pdf")},
        )
        assert resp.status_code == 202

    async def test_result_pending_returns_202(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.extraction_tasks.run_extraction.apply_async", lambda *a, **kw: _mock_task())
        monkeypatch.setattr("app.api.v1.extraction.upload_file", _mock_upload)
        r = await client.post(
            "/api/v1/extraction/bank-statement", headers=auth_headers,
            files={"file": ("b.pdf", io.BytesIO(_make_pdf()), "application/pdf")},
        )
        job_id = r.json()["data"]["id"]
        r2 = await client.get(f"/api/v1/extraction/bank-statement/{job_id}", headers=auth_headers)
        assert r2.status_code == 202   # still pending


# ── Task #10 — Classification ─────────────────────────────────────────────────
class TestClassification:
    async def test_submit_classification(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr("app.workers.classification_tasks.run_classification.apply_async", lambda *a, **kw: _mock_task())
        monkeypatch.setattr("app.api.v1.classification.upload_file", _mock_upload)
        resp = await client.post(
            "/api/v1/classification/submit", headers=auth_headers,
            files={"file": ("doc.pdf", io.BytesIO(_make_pdf()), "application/pdf")},
        )
        assert resp.status_code == 202

    async def test_unsupported_type_rejected(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/classification/submit", headers=auth_headers,
            files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 415


# ── Tasks #8/#9 — Chatbot ─────────────────────────────────────────────────────
class TestChatbot:
    async def test_create_session(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/chat/sessions", headers=auth_headers,
            json={"rag_enabled": True},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["rag_enabled"] is True

    async def test_list_sessions_empty(self, client, auth_headers):
        resp = await client.get("/api/v1/chat/sessions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_get_nonexistent_session(self, client, auth_headers):
        resp = await client.get("/api/v1/chat/sessions/fake-id", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_session(self, client, auth_headers):
        r = await client.post(
            "/api/v1/chat/sessions", headers=auth_headers,
            json={"rag_enabled": False},
        )
        session_id = r.json()["data"]["id"]
        resp = await client.delete(f"/api/v1/chat/sessions/{session_id}", headers=auth_headers)
        assert resp.status_code == 204


# ── Jobs API ──────────────────────────────────────────────────────────────────
class TestJobs:
    async def test_get_nonexistent_job(self, client, auth_headers):
        resp = await client.get("/api/v1/jobs/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    async def test_unauthenticated_job_request(self, client):
        resp = await client.get("/api/v1/jobs/some-id")
        assert resp.status_code == 401