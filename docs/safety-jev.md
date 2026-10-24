# Independent safety and Jev routing

## Conversation limits

- The conversation model may produce up to 1,000 tokens per completion, but its Bahasa Indonesia instructions request concise, complete spoken replies by default.
- The LLM context retains at most 30 completed user turns. Trimming is turn-aware and preserves assistant tool calls with their tool results; orphaned calls/results are removed.
- Jev classifies using a separate, recent eight-message rolling window. Conversation context, Jev event history, and session state stay in memory per call and are not persisted.

## Safety evaluation

`SafetyEngine` runs independently of Jev for each completed user turn. It returns an operational state and reason code, not a diagnosis. The policy prompt asks for clarification of ambiguous statements, empathetic support for distress, and immediate human assistance when danger appears imminent. It never invents emergency numbers or makes calls automatically.

The implementation has deterministic Indonesian and English phrase rules for explicit, ambiguous, and negated expressions. `SafetyStateTracker` keeps elevated handling active over short follow-up turns and permits an explicit contextual negation to de-escalate. The phrase rules are an initial operational gate; they are not a substitute for a comprehensive, evaluated safety classifier. Avoid claiming that this provides clinical assessment.

The call-control layer independently blocks `skip_turn` and automatic conversation-complete hangup for recognized potential-crisis/immediate-danger phrases. If a caller explicitly requests an end while a concern is unresolved, the agent asks one short safety-confirmation question. A caller report of being safe or a repeated explicit end request completes the original request; an ambiguous answer keeps the call active. The confirmation is not proof that the caller is safe. Physical caller hangup always takes precedence.

## Jev classification

Jev is a structured routing recommendation, never a diagnosis. It returns validated personality, intent, confidence, and reasoning code values through the configured OpenRouter model. Routing is deterministic in Python:

- Every call starts `NEUTRAL`.
- Ordinary classification begins after three completed user turns. Explicit advice/referral/information requests may trigger earlier classification.
- Confidence below the configured threshold falls back to neutral.
- A personality switch requires two stable recommendations.
- Safety states above `NEEDS_SUPPORT` bypass classification and apply neutral style plus the safety instruction.
- The same conversation model handles all personalities; personality-specific instructions are versioned in the registry.

Classification history retains only turn number, validated recommendation, confidence, reasoning code, and applied personality for the active call. No transcript text is logged as a Jev event.

## Verification scenarios

Automated tests cover negation, ambiguous distress, immediate-danger phrases, safety-state persistence, Jev warmup, explicit early routing, confidence fallback, invalid provider output, context truncation, and tool-history integrity. Manual evaluation must also cover colloquial Indonesian, code-switching, sarcasm, and varied negation before relying on these phrase-based gates in real use.
