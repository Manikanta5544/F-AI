# Stage 1: Builder (compile dependencies)
FROM python:3.12-slim AS builder

WORKDIR /build

# System dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies into isolated prefix
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Runtime (final image)
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime dependencies (OCR + OpenCV + PDF + system libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    # OpenCV / image processing
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgl1 \
    libjpeg62-turbo \
    zlib1g \
    # DB runtime
    libpq5 \
    # utils
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# ── ENV CONFIG ───────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1

# Install only if playwright exists in requirements
RUN python -m playwright install chromium || true

# ── SECURITY ─────────────────────────────────────────────────────────────────
RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

# ── PORT ─────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── PRODUCTION SERVER ────────────────────────────────────────────────────────
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--timeout-keep-alive", "30", \
     "--log-level", "info"]