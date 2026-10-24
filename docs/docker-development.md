# Docker development

## Requirements

- Docker Engine and Docker Compose.
- A trusted LAN for a separate Linphone device.

## Environment

Copy `.env.example` to `.env` and set all required passwords. Configure the Asterisk LAN subnet and, when using a separate device, the Docker host LAN IP. Keep `.env` untracked.

## Operations

```bash
docker compose up --build
docker compose ps
docker compose logs -f backend
docker compose logs -f asterisk
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health/ready').read().decode())"
```

Readiness reports PostgreSQL, Qdrant, and the Asterisk ARI event connection. The dashboard reports ARI connectivity, not live call activity. OCRmyPDF, Tesseract Indonesian/English language models, Ghostscript and PDF utilities are installed in the backend image. Persistent data is stored in named Docker volumes. The previous MongoDB volume remains unmounted for manual inspection or export.

## Verification

Automated checks include Compose configuration validation, container health, backend readiness, frontend production build, and Asterisk CLI inspection. Linphone registration, two-way RTP audio, and the echo call require manual testing on the local LAN; do not infer them from container health alone.

OCR acceptance requires representative native, scanned, mixed, rotated, Indonesian, and English samples. Record character/word error rate, reading order, OCR processing time, and retrieval results; current automated fixtures verify page/block ordering but do not establish production OCR accuracy.
