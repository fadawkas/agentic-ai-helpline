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

3. Set unique values for `POSTGRES_PASSWORD`, `ASTERISK_SIP_PASSWORD`, and `ASTERISK_ARI_PASSWORD` in `.env`. For the admin dashboard, also set `ADMIN_PASSWORD` and a long random `ADMIN_SESSION_SECRET`. Add provider API keys only if you intend to use those integrations. Never commit `.env`.
4. Start the services:

   ```bash
   docker compose up --build
   ```

The dashboard is available at <http://localhost:5173>. The backend readiness endpoint is <http://localhost:8000/api/health/ready>. Check services and logs with `docker compose ps` and `docker compose logs -f`.

Stop the services with `docker compose down`. Persistent database and service data is stored in Docker named volumes; `docker compose down -v` also deletes that data.

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
- [Voice pipeline plan](docs/phase3-plan.md)

The retrieval evaluation data is provisional and is not a quality benchmark; evaluation results require human review and a held-out dataset.

## Contributing

Contributions and bug reports are welcome. For changes, include relevant tests and documentation, and avoid sharing secrets, private caller information, or unreviewed personal data.

## License

No license is currently specified. All rights are reserved unless a license is added to this repository.
