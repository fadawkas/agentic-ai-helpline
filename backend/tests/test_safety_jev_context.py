import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.jev import AgentPersonality, JevRouter, ReasoningCode, UserIntent
from app.core.config import Settings
from app.safety.engine import (
    SafetyEngine,
    SafetyReasonCode,
    SafetyState,
    SafetyStateTracker,
    SafetyConfirmationState,
    advance_confirmation_state,
    caller_explicitly_requests_end,
)
from app.voice.pipeline import bound_context_messages
from pydantic import SecretStr
from pipecat.processors.aggregators.llm_context import LLMContext


class FakeJevClient:
    def __init__(self, output: dict | Exception):
        self.output = output
        self.calls = 0
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )

    async def create_completion(self, **kwargs):
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        content = json.dumps(self.output)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    async def close(self):
        pass


def jev_settings() -> Settings:
    return Settings(
        postgres_password=SecretStr("postgres"),
        asterisk_ari_username="ari-user",
        asterisk_ari_password=SecretStr("ari-password"),
        openrouter_api_key=SecretStr("openrouter"),
    )


def test_response_and_context_headroom_defaults() -> None:
    settings = jev_settings()

    assert settings.llm_max_output_tokens == 1000
    assert settings.conversation_context_max_turns == 30


def classification(
    personality: str,
    confidence: float = 0.95,
    reasoning_code: str = "EXPRESSED_NEED",
) -> dict:
    return {
        "personality": personality,
        "intent": "EMOTIONAL_SUPPORT",
        "confidence": confidence,
        "reasoning_code": reasoning_code,
    }


@pytest.mark.parametrize(
    ("text", "state", "reason"),
    [
        ("Saya sedang sedih", SafetyState.NEEDS_SUPPORT, SafetyReasonCode.GENERAL_DISTRESS),
        ("Capek hidup", SafetyState.NEEDS_SUPPORT, SafetyReasonCode.AMBIGUOUS_EXPRESSION),
        ("Saya ingin bunuh diri", SafetyState.POTENTIAL_CRISIS, SafetyReasonCode.SELF_HARM_IDEATION),
        ("Saya akan bunuh diri sekarang", SafetyState.IMMEDIATE_DANGER, SafetyReasonCode.IMMEDIATE_INTENT),
        ("Saya tidak ingin bunuh diri", SafetyState.NORMAL, SafetyReasonCode.CONTEXTUAL_NEGATION),
        (
            "Saya tidak ingin bunuh diri tapi mungkin akan melukai diri",
            SafetyState.POTENTIAL_CRISIS,
            SafetyReasonCode.SELF_HARM_IDEATION,
        ),
    ],
)
def test_safety_evaluator_accounts_for_ambiguous_negated_and_urgent_language(
    text, state, reason
) -> None:
    result = SafetyEngine().evaluate(text)

    assert result.state == state
    assert result.reason_code == reason


def test_safety_state_remains_elevated_for_follow_up_turns() -> None:
    tracker = SafetyStateTracker(clear_after_turns=2)
    engine = SafetyEngine()

    assert tracker.update(engine.evaluate("Saya ingin bunuh diri")) == SafetyState.POTENTIAL_CRISIS
    assert tracker.update(engine.evaluate("iya")) == SafetyState.POTENTIAL_CRISIS
    assert tracker.update(engine.evaluate("masih bingung")) == SafetyState.NEEDS_SUPPORT
    assert tracker.update(engine.evaluate("saya ingin bicara soal pekerjaan")) == SafetyState.NORMAL


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Saya aman sekarang", SafetyConfirmationState.CALLER_REPORTS_SAFE),
        ("Tolong akhiri panggilan sekarang", SafetyConfirmationState.CALLER_DECLINES),
        ("Saya tidak tahu", SafetyConfirmationState.CONFIRMATION_PENDING),
    ],
)
def test_safety_confirmation_resolution_requires_a_new_clear_user_turn(text, expected) -> None:
    engine = SafetyEngine()
    evaluation = engine.evaluate(text)

    assert advance_confirmation_state(
        SafetyConfirmationState.CONFIRMATION_PENDING,
        confirmation_turn=5,
        current_turn=6,
        text=text,
        evaluation=evaluation,
    ) == expected


def test_same_turn_retry_cannot_resolve_safety_confirmation() -> None:
    text = "Tolong akhiri panggilan sekarang"
    assert advance_confirmation_state(
        SafetyConfirmationState.CONFIRMATION_PENDING,
        confirmation_turn=5,
        current_turn=5,
        text=text,
        evaluation=SafetyEngine().evaluate(text),
    ) == SafetyConfirmationState.CONFIRMATION_PENDING


@pytest.mark.parametrize(
    "text",
    [
        "Jangan akhiri panggilan, saya masih ingin bicara.",
        "Don't end the call; I still need help.",
    ],
)
def test_negated_end_request_does_not_count_as_caller_declining(text) -> None:
    assert not caller_explicitly_requests_end(text)


@pytest.mark.parametrize("text", [
    "Saya ingin mengakhiri percakapan ini.",
    "Aku mau mengakhiri obrolan sekarang.",
    "Tolong tutup sesi ini.",
    "Bisa kita akhiri percakapan ini?",
    "Sudahi dulu obrolan kita.",
    "Please end this conversation.",
    "I would like to stop our chat.",
])
def test_explicit_conversation_end_request_is_recognized(text) -> None:
    assert caller_explicitly_requests_end(text)


@pytest.mark.parametrize("text", [
    "Saya tidak ingin mengakhiri percakapan ini.",
    "Aku nggak mau mengakhiri obrolan ini.",
    "Jangan tutup sesi ini.",
    "Don’t end this conversation.",
    "I do not want to stop our chat.",
    "Bagaimana cara mengakhiri percakapan?",
    "Saya ingin mengakhiri hidup.",
    "Tolong akhiri hidup saya.",
    "Saya ingin bicara tentang percakapan tadi.",
])
def test_negated_or_unrelated_end_language_does_not_authorize_hangup(text) -> None:
    assert not caller_explicitly_requests_end(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("text,should_end", [
    ("Saya aman sekarang", True),
    ("Saya ingin mengakhiri percakapan ini.", True),
    ("Jangan akhiri panggilan, saya ingin bicara.", False),
    ("Saya tidak tahu", False),
])
async def test_policy_finishes_confirmed_end_without_another_model_tool_call(text, should_end) -> None:
    from app.api.demo import BrowserCallControl, WebSocketState
    from app.agent.orchestration import AgentPolicyProcessor
    from app.agent.state import CallState
    from app.agent.tools import CallControlTools
    from app.telephony.sessions import CallSession
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.frame_processor import FrameDirection

    websocket = AsyncMock()
    websocket.application_state = websocket.client_state = WebSocketState.CONNECTED
    session = CallSession("test", "", "", "")
    session.transition(CallState.ACTIVE)
    session.pending_end_request = True
    session.safety_confirmation_state = SafetyConfirmationState.CONFIRMATION_PENDING
    session.safety_confirmation_turn = 5
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    tools = CallControlTools(session=session, sessions=BrowserCallControl(websocket), tts=object(), playback=playback)
    router = JevRouter(jev_settings(), client=FakeJevClient(classification("NEUTRAL")))
    processor = AgentPolicyProcessor(SafetyEngine(), router, session, tools)
    processor._completed_turns = 5
    processor.push_frame = AsyncMock()
    context = LLMContext(messages=[{"role": "user", "content": text}])
    try:
        await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0)
        if should_end:
            assert session.state == CallState.ENDED
            websocket.close.assert_awaited_once()
            playback.speak_and_wait.assert_awaited_once()
            processor.push_frame.assert_not_awaited()
        else:
            assert session.state == CallState.ACTIVE
            websocket.close.assert_not_awaited()
            processor.push_frame.assert_awaited_once()
    finally:
        await router.close()


@pytest.mark.asyncio
async def test_jev_waits_for_warmup_and_applies_stable_recommendation() -> None:
    client = FakeJevClient(classification("EMPATHETIC_LISTENER"))
    router = JevRouter(jev_settings(), client=client)
    context = LLMContext(messages=[{"role": "user", "content": "Saya ingin cerita."}])

    first = await router.route(context, turn=1, safety_state=SafetyState.NORMAL)
    assert first.personality == AgentPersonality.NEUTRAL
    assert client.calls == 0

    candidate = await router.route(context, turn=3, safety_state=SafetyState.NORMAL)
    assert candidate.personality == AgentPersonality.NEUTRAL
    applied = await router.route(context, turn=4, safety_state=SafetyState.NORMAL)
    assert applied.personality == AgentPersonality.EMPATHETIC_LISTENER
    assert applied.reasoning_code == ReasoningCode.EXPRESSED_NEED
    assert len(router.history) == 3


@pytest.mark.asyncio
async def test_jev_allows_early_explicit_routing_and_low_confidence_falls_back() -> None:
    early_client = FakeJevClient(
        classification("GENTLE_GUIDE", reasoning_code="EXPLICIT_REQUEST")
    )
    early_router = JevRouter(jev_settings(), client=early_client)
    context = LLMContext(messages=[{"role": "user", "content": "Tolong beri saran."}])

    early = await early_router.route(context, turn=1, safety_state=SafetyState.NORMAL)
    assert early.personality == AgentPersonality.GENTLE_GUIDE
    assert early.reasoning_code == ReasoningCode.EXPLICIT_REQUEST

    low_client = FakeJevClient(classification("REFERRAL_SUPPORT", confidence=0.2))
    low_router = JevRouter(jev_settings(), client=low_client)
    low = await low_router.route(context, turn=3, safety_state=SafetyState.NORMAL)
    assert low.personality == AgentPersonality.NEUTRAL
    assert low.reasoning_code == ReasoningCode.LOW_CONFIDENCE


@pytest.mark.asyncio
async def test_jev_safety_override_bypasses_classifier_and_uses_neutral() -> None:
    client = FakeJevClient(classification("REFERRAL_SUPPORT"))
    router = JevRouter(jev_settings(), client=client)
    context = LLMContext(messages=[{"role": "user", "content": "Saya takut."}])

    decision = await router.route(
        context, turn=3, safety_state=SafetyState.POTENTIAL_CRISIS
    )

    assert decision.personality == AgentPersonality.NEUTRAL
    assert decision.reasoning_code == ReasoningCode.SAFETY_OVERRIDE
    assert client.calls == 0


@pytest.mark.asyncio
async def test_jev_invalid_provider_output_falls_back_to_neutral() -> None:
    client = FakeJevClient(classification("NOT_A_PERSONALITY"))
    router = JevRouter(jev_settings(), client=client)
    context = LLMContext(messages=[{"role": "user", "content": "Saya ingin cerita."}])

    decision = await router.route(context, turn=3, safety_state=SafetyState.NORMAL)

    assert decision.personality == AgentPersonality.NEUTRAL
    assert decision.reasoning_code == ReasoningCode.INVALID_RECOMMENDATION


def test_context_window_keeps_thirty_turns_and_tool_exchange_together() -> None:
    messages = [{"role": "system", "content": "base instructions"}]
    for turn in range(32):
        messages.append({"role": "user", "content": f"user {turn}"})
        if turn == 4:
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "tool-4", "type": "function", "function": {"name": "skip_turn", "arguments": "{}"}}],
                }
            )
            messages.append({"role": "tool", "tool_call_id": "tool-4", "content": "skipped"})
        messages.append({"role": "assistant", "content": f"assistant {turn}"})

    retained = bound_context_messages(messages, max_turns=30)
    user_turns = [message["content"] for message in retained if message.get("role") == "user"]
    retained_tool_ids = {
        message.get("tool_call_id")
        for message in retained
        if message.get("role") == "tool"
    }
    retained_call_ids = {
        call["id"]
        for message in retained
        for call in message.get("tool_calls", [])
    }

    assert user_turns == [f"user {turn}" for turn in range(2, 32)]
    assert retained_tool_ids == retained_call_ids == {"tool-4"}


def test_context_window_removes_orphaned_tool_calls_but_keeps_user_turn() -> None:
    messages = [
        {"role": "user", "content": "latest"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "missing-result", "type": "function", "function": {"name": "skip_turn", "arguments": "{}"}}],
        },
    ]

    retained = bound_context_messages(messages, max_turns=30)

    assert retained == [messages[0]]
