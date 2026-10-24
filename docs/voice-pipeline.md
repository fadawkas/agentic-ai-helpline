# Phase 2 media pipeline

## Call route

```text
Linphone → PJSIP → Asterisk Stasis (7000)
                       │
                       ├── ARI events and call control
                       │
                       └── chan_websocket media
                                  │
                                  ▼
                         FastAPI /media
                                  │
                          Pipecat voice pipeline
```

Extension `7000` enters the configured Stasis application. The backend creates one mixing bridge, a per-call external-media channel, and one Pipecat pipeline. The media WebSocket is a distinct Asterisk-to-backend connection; it is not the ARI event WebSocket. `7001` remains the direct Asterisk echo diagnostic.

The WebSocket transport uses the community `pipecat-asterisk` package and its Asterisk serializer and output flow control. Asterisk sends JSON text control frames and binary `slin16` audio. Pipecat runs at 16 kHz mono. With `VOICE_AGENT_ENABLED=true`, each call gets Deepgram Nova-3 transcription, Silero VAD + Smart Turn V3, an OpenRouter conversational model and Jev routing, direct Fish Audio streaming TTS, and validated `skip_turn` / `end_call` tools. `end_call` transitions the call to `ENDING`, interrupts active output, waits for the farewell's playback completion or bounded timeout, then invokes idempotent ARI cleanup. If a caller explicitly asks to end while a safety concern is unresolved, the agent asks one short confirmation question; a caller report of being safe or a repeated explicit request completes the original end request, while an ambiguous answer keeps the call active. A caller hangup always takes precedence. `skip_turn` interrupts output without asking the LLM to generate another response. The deterministic phrase-based safety evaluator and tracker are initial safeguards, not a comprehensive safety system. With the flag false, the pipeline stays in audio loopback mode. Audio and transcript content are not persisted by the pipeline.

The random session identifier is passed as a WebSocket URI parameter and is used to attach the media connection to its call. ARI channel IDs, bridge IDs, media pipeline tasks, and cleanup state are isolated per call.

## Lifecycle and failure behavior

Call state transitions are `CONNECTING → ACTIVE → ENDING → ENDED`. Caller hangup, media disconnect, setup failure, and application shutdown enter one idempotent cleanup path. It cancels setup/pipeline tasks, hangs up owned channels, destroys the bridge, and removes the in-memory session. ARI event reconnects reconcile tracked calls against Asterisk's active channel list.

The backend reconnects to ARI with bounded exponential backoff. Readiness includes the ARI event connection as well as PostgreSQL and Qdrant connectivity. API credentials stay in the backend environment; ARI is not published as a host port.

## Verification

Run backend tests and image checks through Compose. On a supported host kernel with all services healthy:

1. Register Linphone as `1001`.
2. Call `7001` and verify direct Asterisk echo.
3. With `VOICE_AGENT_ENABLED=false`, call `7000` and verify Pipecat loopback audio.
4. With provider settings configured and `VOICE_AGENT_ENABLED=true`, call `7000` and verify a short Indonesian conversation.
5. Ask the assistant to stay silent, then speak again and verify it resumes listening.
6. Ask the assistant to end the call; verify one farewell finishes before disconnect and that cleanup leaves no channels.
7. Hang up, then check `docker compose exec asterisk asterisk -rx 'core show channels'` for cleanup.
8. Repeat with simultaneous calls using separate SIP identities to check session isolation.

The real Linphone call is a manual LAN test; container health or unit tests do not prove bidirectional phone audio.
