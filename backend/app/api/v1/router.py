"""Master APIRouter for /api/v1 — includes all domain sub-routers."""
from fastapi import APIRouter

from app.api.v1 import auth, jobs, ocr, scraper, extraction, classification, chatbot, download

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_router.include_router(ocr.router, prefix="/ocr", tags=["OCR"])
api_router.include_router(scraper.router, prefix="/scraper", tags=["Scraper"])
api_router.include_router(extraction.router, prefix="/extraction")
api_router.include_router(classification.router, prefix="/classification", tags=["Classification"])
api_router.include_router(chatbot.router, prefix="/chatbot", tags=["Chatbot"])
api_router.include_router(download.router, prefix="/download", tags=["Download"])
