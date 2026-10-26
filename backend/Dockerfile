FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng \
    ghostscript qpdf unpaper pngquant jbig2dec fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir .
RUN pip install --no-cache-dir ocrmypdf
COPY app ./app
COPY tests ./tests
COPY knowledge ./knowledge

FROM base AS development
RUN pip install --no-cache-dir "uvicorn[standard]" watchfiles '.[test]'
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS evaluation
RUN pip install --no-cache-dir '.[evaluation]'
CMD ["python", "-m", "app.rag.evaluate_ragas"]
