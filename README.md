# Indonesian AI Voice Support

A voice-first support platform for Indonesian callers, combining SIP telephony, a real-time voice agent, and a curated knowledge base. The project includes a React dashboard, FastAPI backend, Asterisk PBX, PostgreSQL, and Qdrant, orchestrated locally with Docker Compose.

> **Project status:** This is an active development project. AI responses and retrieval evaluation are experimental and are not a substitute for professional mental health care. Do not use this project as a production or emergency response service.

## Features

- Asterisk SIP calling with ARI call control and a Pipecat voice pipeline.
- Indonesian speech recognition and speech synthesis integrations.
- Conversational routing and an independent safety layer.
- Curated, source-verified knowledge retrieval with dense and BM25 search.
- Admin dashboard for managing knowledge documents.
- Docker Compose development environment with health checks.

## Architecture

| Component | Technology |
| --- | --- |
| Dashboard | React, TypeScript, Vite, Tailwind CSS |
| API | Python 3.12+, FastAPI, Pydantic |
| Voice agent | Pipecat |
| Telephony | Asterisk, SIP, ARI, Linphone |
| Application database | PostgreSQL |
| Vector search | Qdrant |
| Local development | Docker Compose |

External AI services are optional/configured through environment variables. See `.env.example` for available settings.

## Requirements

- Docker Engine
- Docker Compose v2
- Git

## Quick start

1. Clone the repository and enter its directory.
2. Create your local environment file:

   ```bash
   cp .env.example .env
   ```

3. Set a unique `POSTGRES_PASSWORD` in `.env`. SIP/ARI passwords are required only if you enable optional telephony. For the admin dashboard, also set `ADMIN_PASSWORD` and a long random `ADMIN_SESSION_SECRET`. Set `OPENROUTER_API_KEY` to enable RAG indexing and retrieval. Add the Deepgram and Fish Audio keys only if you intend to enable the live voice agent. Never commit `.env`.
4. Start the services:

   ```bash
   docker compose up --build
   ```

The dashboard is available at <http://localhost:5173>. The backend readiness endpoint is <http://localhost:8000/api/health/ready>. Check services and logs with `docker compose ps` and `docker compose logs -f`.

Stop the services with `docker compose down`. Persistent database and service data is stored in Docker named volumes; `docker compose down -v` also deletes that data.

## Browser voice demo (no login or SIP)

Open <http://localhost:5173/demo> or use **Mulai percakapan** in the dashboard header. Click **Hubungkan dengan AI**, allow microphone access, and speak in Indonesian. **Akhiri percakapan** disconnects and releases the microphone.

The page connects to `/api/demo/voice` over WebSocket and reuses the existing STT → agent/knowledge base → TTS pipeline without creating an Asterisk channel or SIP call. Enable `VOICE_AGENT_ENABLED=true` and configure `DEEPGRAM_API_KEY`, `OPENROUTER_API_KEY`, `FISH_AUDIO_API_KEY`, and `FISH_REFERENCE_ID` in `.env`; the knowledge base must be initialized. Restart the backend after configuration changes. By default `TELEPHONY_ENABLED=false`, and the browser-only stack does not start or require Asterisk. Set `TELEPHONY_ENABLED=true` in `.env`, configure `ASTERISK_SIP_PASSWORD` and `ASTERISK_ARI_PASSWORD`, and run `docker compose --profile telephony up --build` to enable SIP calling. When telephony is enabled, backend readiness requires ARI to connect. To switch back, set `TELEPHONY_ENABLED=false`, run `docker compose --profile telephony stop asterisk`, and recreate the backend with `docker compose up -d --build`.

Microphone access requires **HTTPS or localhost**; a plain HTTP LAN address will not work. The Vite proxy supports WebSocket upgrades; production reverse proxies must forward `/api/demo/voice` upgrades and preserve the public Host header. Audio uses mono PCM16 at 16 kHz. The demo is public, limited to five minutes per session and three concurrent sessions and six new sessions per rolling minute per backend process, and rejects cross-origin browser connections. These limits are shared by all users on that process, reset on restart, and multiply across workers. If playback falls more than two seconds behind, the client ends the session with a visible error instead of silently skipping speech. These basic limits are not abuse prevention: add proxy-level rate limiting and usage monitoring before exposing it broadly. Voice/AI provider usage may incur charges.

## Start the RAG knowledge base

RAG needs a valid `OPENROUTER_API_KEY` in `.env` for embeddings, source validation, and reranking. Start the services with `docker compose up --build`; when the key is configured, the backend initializes Qdrant and automatically validates and indexes the bundled Indonesian baseline. Without the key, the rest of the app can start, but knowledge indexing and retrieval are unavailable.

To manage additional documents, set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_SESSION_SECRET` in `.env`, start the dashboard, and sign in at <http://localhost:5173>. Upload reviewed source material with its publisher, official source URL, and verification date. Only documents that pass the configured official-source validation are indexed. See the [RAG guide](docs/rag-knowledge-base.md) for supported formats and document requirements.

### Evaluate retrieval

With the services running and `OPENROUTER_API_KEY` configured, run the included labeled evaluation set:

```bash
docker compose exec backend python -m app.rag.evaluate --file /app/knowledge/rag-evaluation.json --k 4
```

The custom evaluator reports retrieval ranking metrics and, by default, generates grounded answers and sends them with retrieved passages to an OpenRouter model judge. Use `--retrieval-only` to skip answer generation and judging (embeddings and reranking are still used). These provider calls may incur charges. The bundled dataset is small and provisional; its scores are not a benchmark.

To run RAGAS against a temporary Qdrant collection populated only from the checked-in baseline fixtures (not user uploads), use the optional evaluation service:

```bash
docker compose --profile evaluation run --rm ragas-evaluator \
  python -m app.rag.evaluate_ragas \
  --file /app/knowledge/rag-evaluation.json \
  --output /app/knowledge/ragas-evaluation-results.json
```

The RAGAS evaluator requires `OPENROUTER_API_KEY`, creates and removes its own Qdrant collection, and records dataset/corpus hashes and model versions in its report. It makes embedding, reranking, answer-generation, and judge requests to OpenRouter; these may incur charges. It uses only the synthetic evaluation questions and checked-in baseline content, not saved caller data.

### Latest RAGAS smoke results

RAGAS **0.4.3**, evaluated **2026-10-24**, `k=4`, eight cases (six answerable, two unanswerable):

| Metric | Result |
| --- | ---: |
| Context precision | 1.000 (6 cases) |
| Context recall | 1.000 (6 cases) |
| Faithfulness | 0.824 (6 cases) |
| Factual correctness | 0.333 (6 cases) |
| No-answer accuracy (project metric) | 1.000 (2 cases) |

The [full RAGAS report](backend/knowledge/ragas-evaluation-results.json) includes retrieved baseline passages, answers, per-case scores, corpus and dataset hashes, and model metadata. No-answer accuracy is a project-specific check, not a RAGAS metric. These are LLM-judged smoke-test results on a small provisional set, not a quality benchmark. The low factual-correctness score should be reviewed against the reference answers; have a human review the labels and judgments, then expand separate development and held-out datasets before using scores to claim quality. The earlier [custom evaluator report](backend/knowledge/rag-evaluation-results.json) is retained for comparison; it used the live corpus and is not directly comparable to the isolated RAGAS run.

## Test and build

Run the backend test suite and frontend production build inside their Compose services:

```bash
docker compose exec backend python -m pytest -q
docker compose exec frontend npm run build
```

## Try the SIP echo test

On a trusted local network, register Linphone to the Docker host's LAN IP using:

- Username/authentication ID: `1001`
- Password: the `ASTERISK_SIP_PASSWORD` from `.env`
- Transport: UDP, port `5060`
- Registration server: the Docker host's LAN IP

Call extension `7001` for Asterisk's direct echo diagnostic, or `7000` for the application media loopback. These test extensions do not connect to the AI provider pipeline. The host firewall must allow UDP `5060` and the configured RTP range (default `10000–10100`) from the trusted LAN. Do not expose ARI or database services publicly.

## Documentation

- [Docker development](docs/docker-development.md)
- [Telephony setup](docs/telephony.md)
- [Voice pipeline](docs/voice-pipeline.md)
- [Safety and Jev routing](docs/safety-jev.md)
- [RAG knowledge base and evaluation](docs/rag-knowledge-base.md)

## Contributing

Contributions and bug reports are welcome. For changes, include relevant tests and documentation, and avoid sharing secrets, private caller information, or unreviewed personal data.

## License

No license is currently specified. All rights are reserved unless a license is added to this repository.
