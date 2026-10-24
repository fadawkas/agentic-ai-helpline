# Phase 3 — Basic Indonesian Voice Agent

## Goal

Turn the verified Asterisk → FastAPI → Pipecat audio loopback on extension `7000` into a basic Indonesian conversational voice agent. Keep extension `7001` as the direct Asterisk echo diagnostic.

## Provider choices

- **STT:** Deepgram Nova-3 streaming, with `language=id`. Deepgram's current model documentation lists Indonesian support for Nova-3. Use the direct Deepgram API and its signup credits; these credits are introductory rather than an unlimited free tier.
- **Turn detection:** Silero VAD and Pipecat Smart Turn V3, initially. Do not use Flux for Indonesian: Deepgram's documented Flux language list currently omits Indonesian.
- **Conversation:** OpenRouter model `deepseek/deepseek-v4.1-flash-1017`, verified in the OpenRouter model catalog. It supports streaming and tool-related parameters; tools are outside Phase 3 scope.
- **TTS:** Direct Fish Audio API using `s2.1-pro-free`. Fish currently lists this API model at $0.00 per million UTF-8 bytes. It supports HTTP audio chunk streaming and a WebSocket mode for incrementally arriving LLM text. Free-tier latency/availability limits and Indonesian voice quality must be evaluated in actual calls.
- **Call controls:** OpenRouter native function calling for validated `skip_turn` and `end_call`. These controls use Python-side Pydantic validation and session state; LLM output is never executed as code.

## Implementation sequence

1. **Provider configuration:** Add typed backend settings and pass API credentials/model choices from Compose to the backend only. Validate required settings when voice-agent integration is enabled, without making provider keys necessary for the foundational stack to start. Never expose credentials to the frontend or log secrets/transcripts.
2. **Streaming STT:** Feed per-call audio to Deepgram Nova-3 using Indonesian and the supported input encoding. Handle interim and final results; only completed turns should ordinarily trigger conversation. Bound connection, response, and shutdown waits.
3. **Turn orchestration:** Integrate Silero VAD and Smart Turn V3 at turn boundaries. Request or await a finalized transcript with a bounded timeout; avoid duplicate requests and preserve the existing per-call isolation and cancellation lifecycle.
4. **Neutral conversation:** Send completed user turns to OpenRouter using the configured DeepSeek model. Maintain bounded context per call; produce concise Bahasa Indonesia responses, with supportive non-diagnostic behavior and clear limits. Handle provider errors, rate limits, timeouts, and hangup cancellation.
5. **Streaming speech output:** Send assistant text to Fish Audio directly using `s2.1-pro-free`, `FISH_REFERENCE_ID`, Indonesian normalization, and a low-latency streaming mode. Decode/resample supported Fish output to the Asterisk/Pipecat output format and stop synthesis/playback on interruption or hangup.
6. **Call-control tools:** Add typed `skip_turn` and `end_call` schemas to each call context. A skip stops current playback without triggering another model response, except when the recent user turn contains conservative safety concern indicators. End-call requires an explicit recent user request or a normal-completion decision; it transitions the session to `ENDING`, stops current output, speaks a bounded farewell, waits for output playback completion or timeout, then uses idempotent ARI cleanup. Safety phrase matching is an interim gate, not a replacement for the independent safety engine in Phase 4.
7. **Evaluation:** Exercise a complete Indonesian phone conversation on extension `7000`; measure speech-final-to-first-audio latency; check transcription quality, silence/pause turn-taking, interruptions, tool-call validation, farewell playback/hangup order, provider failure, caller hangup, cleanup, and concurrent-session separation. Retain no audio or private transcripts by default.

## Acceptance criteria

- `7001` remains a working direct Asterisk echo diagnostic.
- `7000` supports a short two-way Indonesian AI conversation without duplicate responses.
- Audio remains isolated to each call; caller hangup cancels pending STT, LLM, and TTS work and releases resources.
- Provider failures/timeouts do not crash the backend or strand the call pipeline.
- Automated provider/orchestration tests pass through Docker Compose, followed by a documented manual phone test.
- Latency and operational errors can be measured without logging private transcript content.

## Manual prerequisites

Set `DEEPGRAM_API_KEY`, `OPENROUTER_API_KEY`, and `FISH_AUDIO_API_KEY` in the private `.env`. Choose a Fish Audio voice from its library and place its model reference ID in `FISH_REFERENCE_ID`. API usage may incur charges: Deepgram's signup credits are limited, OpenRouter conversation calls are metered, and Fish's selected free model has its own availability/rate limits.

## Provider references checked

- [Deepgram pricing](https://deepgram.com/pricing)
- [Deepgram models and languages](https://developers.deepgram.com/docs/models-languages-overview)
- [OpenRouter model record](https://openrouter.ai/api/v1/model/deepseek/deepseek-v4.1-flash-1017)
- [Fish Audio quick start](https://docs.fish.audio/developer-guide/getting-started/quickstart)
- [Fish Audio realtime streaming](https://docs.fish.audio/features/realtime-streaming)
- [Fish Audio pricing and rate limits](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits)
