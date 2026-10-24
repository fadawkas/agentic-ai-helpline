import asyncio
import pytest
from pydantic import SecretStr
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.config import Settings
from app.agent.tools import CallControlTools
from app.agent.state import CallState
from app.safety.engine import SafetyConfirmationState, SafetyState
from app.telephony.sessions import CallSession
from app.voice.pipeline import PlaybackCompletionTracker, bound_context_messages
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallResultProperties,
    InterruptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext


def make_settings(**overrides) -> Settings:
    values = {
        "postgres_password": SecretStr("postgres"),
        "asterisk_ari_username": "ari-user",
        "asterisk_ari_password": SecretStr("ari-password"),
        "deepgram_api_key": None,
        "openrouter_api_key": None,
        "fish_audio_api_key": None,
        "fish_reference_id": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_voice_agent_configuration_requires_provider_keys_and_voice() -> None:
    settings = make_settings()

    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY") as error:
        settings.validate_voice_agent()

    assert "OPENROUTER_API_KEY" in str(error.value)
    assert "FISH_AUDIO_API_KEY" in str(error.value)
    assert "FISH_REFERENCE_ID" in str(error.value)


def test_voice_agent_configuration_accepts_complete_provider_setup() -> None:
    settings = make_settings(
        deepgram_api_key=SecretStr("deepgram"),
        openrouter_api_key=SecretStr("openrouter"),
        fish_audio_api_key=SecretStr("fish"),
        fish_reference_id="voice-model-id",
    )

    settings.validate_voice_agent()


def test_conversation_context_keeps_system_message_and_recent_turns() -> None:
    messages = [{"role": "system", "content": "instructions"}]
    messages.extend(
        {"role": role, "content": f"turn {index}"}
        for index in range(4)
        for role in ("user", "assistant")
    )

    bounded = bound_context_messages(messages, max_turns=2)

    assert bounded == [messages[0], *messages[-4:]]


@pytest.mark.asyncio
async def test_agent_response_reaches_tts_before_assistant_aggregation(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock
    from pipecat.frames.frames import TextFrame
    from app.voice import pipeline as voice

    settings = make_settings(
        deepgram_api_key=SecretStr("deepgram"),
        openrouter_api_key=SecretStr("openrouter"),
        fish_audio_api_key=SecretStr("fish"),
        fish_reference_id="voice-model-id",
    )
    session = CallSession("a" * 32, "caller", "bridge", "media", state=CallState.ACTIVE)
    tts = Mock()
    assistant = Mock()
    transport = Mock()
    aggregators = Mock()
    aggregators.assistant.return_value = assistant
    monkeypatch.setattr(voice, "AsteriskWebsocketTransport", Mock(return_value=transport))
    monkeypatch.setattr(voice, "DeepgramSTTService", Mock())
    monkeypatch.setattr(voice, "DiagnosticOpenAILLMService", Mock())
    monkeypatch.setattr(voice, "FishAudioTTSService", Mock(return_value=tts))
    monkeypatch.setattr(voice, "SileroVADAnalyzer", Mock())
    monkeypatch.setattr(voice, "LocalSmartTurnAnalyzerV3", Mock())
    monkeypatch.setattr(voice, "LLMContextAggregatorPair", Mock(return_value=aggregators))
    pipeline_factory = Mock()
    monkeypatch.setattr(voice, "Pipeline", pipeline_factory)
    monkeypatch.setattr(voice, "PipelineWorker", Mock())
    monkeypatch.setattr(voice, "WorkerRunner", Mock(return_value=Mock(
        add_workers=AsyncMock(), run=AsyncMock(),
    )))

    await voice.run_voice_agent(
        Mock(), settings, asyncio.Event(), session, Mock(), Mock()
    )
    llm = voice.DiagnosticOpenAILLMService.return_value
    assert [call.args[0] for call in llm.register_function.call_args_list] == [
        "skip_turn",
        "end_call",
        "search_knowledge_base",
        "get_mental_health_information",
        "get_verified_referral_resources",
    ]
    processors = pipeline_factory.call_args.args[0]
    # The real assistant aggregator consumes TextFrame instead of forwarding it.
    # Exercise response traversal with that boundary behavior.
    spoken = []
    for processor in processors:
        if processor is assistant:
            break
        if processor is tts:
            spoken.append(TextFrame("Halo.").text)
    assert spoken == ["Halo."], (processors, tts, assistant)
    assert processors.index(transport.output()) < processors.index(assistant)


def make_tool_call(arguments: dict, text: str = ""):
    context = LLMContext()
    if text:
        context.add_message({"role": "user", "content": text})
    callback = AsyncMock()
    return SimpleNamespace(arguments=arguments, context=context, result_callback=callback)


def make_call_control(*, playback=None, manager=None):
    session = CallSession("b" * 32, "caller", "bridge", "media", state=CallState.ACTIVE)
    return (
        CallControlTools(
            session=session,
            sessions=manager or SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock()),
            tts=AsyncMock(),
            playback=playback or SimpleNamespace(
                interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock()
            ),
        ),
        session,
    )


def test_control_tool_schemas_have_validated_handlers() -> None:
    tools, _ = make_call_control()

    schemas = tools.schemas()

    assert [schema.name for schema in schemas] == ["skip_turn", "end_call"]
    assert all(schema.handler is None for schema in schemas)


@pytest.mark.asyncio
async def test_skip_turn_stops_playback_without_restarting_llm() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    tools, _ = make_call_control(playback=playback)
    params = make_tool_call({"reason": "USER_REQUESTED_SILENCE"})

    await tools.skip_turn(params)

    playback.interrupt_and_wait.assert_awaited_once()
    playback.speak_and_wait.assert_not_awaited()
    result = params.result_callback.await_args
    assert result.args[0]["status"] == "skipped"
    assert result.kwargs["properties"].run_llm is False


@pytest.mark.asyncio
async def test_skip_turn_cannot_silence_a_recent_safety_concern() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    tools, _ = make_call_control(playback=playback)
    params = make_tool_call(
        {"reason": "WAITING_FOR_USER"}, "Saya ingin mengakhiri hidup saya."
    )

    await tools.skip_turn(params)

    playback.interrupt_and_wait.assert_not_awaited()
    result = params.result_callback.await_args
    assert result.args[0]["status"] == "rejected"
    assert result.kwargs["properties"].run_llm is True


@pytest.mark.asyncio
async def test_end_call_requires_explicit_user_request_and_validated_arguments() -> None:
    tools, _ = make_call_control()
    params = make_tool_call({"reason": "USER_REQUEST"}, "Saya ingin bercerita.")

    await tools.end_call(params)

    result = params.result_callback.await_args
    assert result.args[0]["reason"] == "no_explicit_user_request"
    result.kwargs["properties"].run_llm is True


@pytest.mark.asyncio
async def test_conversation_complete_cannot_end_call_after_safety_concern() -> None:
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock())
    tools, _ = make_call_control(manager=manager)
    params = make_tool_call(
        {"reason": "CONVERSATION_COMPLETE"}, "Saya ingin bunuh diri."
    )

    await tools.end_call(params)

    manager.begin_ending.assert_not_awaited()
    result = params.result_callback.await_args
    assert result.args[0]["status"] == "rejected"
    assert result.kwargs["properties"].run_llm is True


@pytest.mark.asyncio
async def test_invalid_tool_arguments_never_execute_control_action() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock())
    tools, _ = make_call_control(playback=playback, manager=manager)
    params = make_tool_call({"reason": "DROP_EVERYTHING"})

    await tools.skip_turn(params)

    playback.interrupt_and_wait.assert_not_awaited()
    manager.begin_ending.assert_not_awaited()
    assert params.result_callback.await_args.args[0]["reason"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_end_call_waits_for_farewell_then_schedules_idempotent_cleanup() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock())
    tools, session = make_call_control(playback=playback, manager=manager)
    params = make_tool_call(
        {"reason": "USER_REQUEST", "farewell": "Baik, sampai jumpa."},
        "Tolong akhiri panggilan sekarang.",
    )

    await tools.end_call(params)
    await asyncio.sleep(0)

    assert session.state == CallState.ACTIVE  # The fake manager omits its state transition.
    manager.begin_ending.assert_awaited_once_with(session)
    playback.interrupt_and_wait.assert_awaited_once()
    playback.speak_and_wait.assert_awaited_once_with(
        tools._tts, "Baik, sampai jumpa."
    )
    manager.end_call.assert_awaited_once_with(session, hangup_caller=True)
    assert params.result_callback.await_args.kwargs["properties"].run_llm is False


@pytest.mark.asyncio
async def test_playback_tracker_waits_for_output_stop_acknowledgment() -> None:
    tracker = PlaybackCompletionTracker()

    class FakeTTS:
        async def queue_frame(self, frame):
            if isinstance(frame, TTSSpeakFrame):
                await tracker.observe(BotStartedSpeakingFrame(), direction)
                await tracker.observe(BotStoppedSpeakingFrame(), direction)

    from pipecat.processors.frame_processor import FrameDirection
    direction = FrameDirection.DOWNSTREAM
    await tracker.speak_and_wait(FakeTTS(), "Sampai jumpa.", timeout=0.1)


@pytest.mark.asyncio
async def test_lookup_acknowledgment_is_interruptible() -> None:
    tracker = PlaybackCompletionTracker()
    from pipecat.processors.frame_processor import FrameDirection

    direction = FrameDirection.DOWNSTREAM

    class InterruptingTTS:
        async def queue_frame(self, frame):
            if isinstance(frame, TTSSpeakFrame):
                await tracker.observe(BotStartedSpeakingFrame(), direction)
                await tracker.observe(InterruptionFrame(), direction)

    await tracker.speak_acknowledgment(
        InterruptingTTS(), "Sebentar ya, saya cek informasinya dulu.", timeout=0.1
    )


@pytest.mark.asyncio
async def test_playback_interrupt_waits_for_output_stop_acknowledgment() -> None:
    tracker = PlaybackCompletionTracker()
    from pipecat.processors.frame_processor import FrameDirection

    direction = FrameDirection.DOWNSTREAM
    await tracker.observe(BotStartedSpeakingFrame(), direction)

    class FakeTTS:
        async def queue_frame(self, frame):
            assert isinstance(frame, InterruptionFrame)
            await tracker.observe(frame, direction)
            await tracker.observe(BotStoppedSpeakingFrame(), direction)

    await tracker.interrupt_and_wait(FakeTTS(), timeout=0.1)


@pytest.mark.asyncio
async def test_speak_timeout_is_one_deadline_for_start_and_stop() -> None:
    tracker = PlaybackCompletionTracker()
    from pipecat.processors.frame_processor import FrameDirection

    direction = FrameDirection.DOWNSTREAM

    class SlowTTS:
        async def queue_frame(self, frame):
            async def playback_events():
                await asyncio.sleep(0.03)
                await tracker.observe(BotStartedSpeakingFrame(), direction)
                await asyncio.sleep(0.08)
                await tracker.observe(BotStoppedSpeakingFrame(), direction)

            asyncio.create_task(playback_events())

    with pytest.raises(TimeoutError):
        await tracker.speak_and_wait(SlowTTS(), "pertanyaan", timeout=0.09)
    await asyncio.sleep(0.03)


@pytest.mark.asyncio
async def test_confirmation_playback_timeout_does_not_trigger_an_automatic_repeat() -> None:
    playback = SimpleNamespace(
        interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock(side_effect=TimeoutError)
    )
    tools, session = make_call_control(playback=playback)
    session.safety_state = SafetyState.POTENTIAL_CRISIS
    params = make_tool_call(
        {"reason": "USER_REQUEST"}, "Tolong akhiri panggilan sekarang."
    )

    await tools.end_call(params)

    assert session.safety_confirmation_state == SafetyConfirmationState.CONFIRMATION_PENDING
    callback = params.result_callback.await_args
    assert callback.args[0]["status"] == "confirmation_pending_audio_timeout"
    assert callback.kwargs["properties"].run_llm is False


@pytest.mark.asyncio
async def test_call_session_can_enter_ending_before_playback_cleanup() -> None:
    from app.telephony.sessions import CallSessionManager

    class FakeAri:
        def __init__(self):
            self.hangups = []

        async def hangup(self, channel_id):
            self.hangups.append(channel_id)

        async def destroy_bridge(self, bridge_id):
            pass

        async def create_bridge(self, bridge_id):
            pass

        async def add_channels(self, bridge_id, channel_ids):
            pass

        async def answer(self, channel_id):
            pass

        async def create_media_channel(self, *, session_id, channel_id):
            pass

    ari = FakeAri()
    manager = CallSessionManager(ari)
    session = await manager.start_call("caller-tool-test")
    session.transition(CallState.ACTIVE)

    assert await manager.begin_ending(session) is True
    assert await manager.begin_ending(session) is False
    await manager.end_call(session, hangup_caller=True)
    await manager.end_call(session, hangup_caller=True)

    assert session.state == CallState.ENDED
    assert ari.hangups.count(session.caller_channel_id) == 1


@pytest.mark.asyncio
async def test_explicit_end_request_during_crisis_starts_confirmation_instead_of_hanging_up() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock())
    tools, session = make_call_control(playback=playback, manager=manager)
    params = make_tool_call({"reason": "CONVERSATION_COMPLETE"}, "Saya ingin bunuh diri.")
    params.context.add_message({"role": "user", "content": "Tolong akhiri panggilan sekarang."})
    await tools.end_call(params)
    manager.begin_ending.assert_not_awaited()
    manager.end_call.assert_not_awaited()
    assert session.safety_confirmation_state == SafetyConfirmationState.CONFIRMATION_PENDING
    assert playback.speak_and_wait.await_args.args[1].startswith("Sebelum kita akhiri")
    assert params.result_callback.await_args.args[0]["status"] == "safety_confirmation_required"


@pytest.mark.asyncio
async def test_first_end_request_during_crisis_asks_once_without_hanging_up() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock())
    tools, session = make_call_control(playback=playback, manager=manager)
    session.safety_state = SafetyState.POTENTIAL_CRISIS
    session.completed_user_turns = 3
    params = make_tool_call(
        {"reason": "USER_REQUEST"}, "Tolong akhiri panggilan sekarang."
    )

    await tools.end_call(params)

    assert session.state == CallState.ACTIVE
    assert session.safety_confirmation_state == SafetyConfirmationState.CONFIRMATION_PENDING
    assert session.safety_confirmation_turn == 3
    assert session.pending_end_request is True
    assert playback.speak_and_wait.await_args.args[1].startswith(
        "Sebelum kita akhiri"
    )
    manager.begin_ending.assert_not_awaited()
    manager.end_call.assert_not_awaited()
    assert params.result_callback.await_args.args[0]["status"] == "safety_confirmation_required"
    assert params.result_callback.await_args.kwargs["properties"].run_llm is False


@pytest.mark.asyncio
async def test_repeated_tool_call_in_confirmation_turn_does_not_repeat_question() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    tools, session = make_call_control(playback=playback)
    session.pending_end_request = True
    session.safety_confirmation_state = SafetyConfirmationState.CONFIRMATION_PENDING
    session.completed_user_turns = 4
    session.safety_confirmation_turn = 4
    session.safety_confirmation_prompted_turn = 4
    params = make_tool_call(
        {"reason": "USER_REQUEST"}, "Tolong akhiri panggilan sekarang."
    )

    await tools.end_call(params)

    playback.speak_and_wait.assert_not_awaited()
    assert params.result_callback.await_args.args[0]["status"] == "safety_confirmation_pending"
    assert params.result_callback.await_args.kwargs["properties"].run_llm is False


@pytest.mark.asyncio
async def test_confirmed_pending_end_speaks_farewell_then_cleans_up() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=True), end_call=AsyncMock())
    tools, session = make_call_control(playback=playback, manager=manager)
    session.pending_end_request = True
    session.safety_confirmation_state = SafetyConfirmationState.CALLER_REPORTS_SAFE

    assert await tools.finish_after_confirmation() is True
    await asyncio.sleep(0)

    manager.begin_ending.assert_awaited_once_with(session)
    playback.speak_and_wait.assert_awaited_once()
    manager.end_call.assert_awaited_once_with(session, hangup_caller=True)
    assert session.pending_end_request is False


@pytest.mark.asyncio
async def test_caller_hangup_wins_before_confirmed_end_farewell() -> None:
    playback = SimpleNamespace(interrupt_and_wait=AsyncMock(), speak_and_wait=AsyncMock())
    manager = SimpleNamespace(begin_ending=AsyncMock(return_value=False), end_call=AsyncMock())
    tools, session = make_call_control(playback=playback, manager=manager)
    session.state = CallState.ENDED
    session.pending_end_request = True
    session.safety_confirmation_state = SafetyConfirmationState.CALLER_DECLINES

    assert await tools.finish_after_confirmation() is False
    playback.speak_and_wait.assert_not_awaited()
    manager.end_call.assert_not_awaited()


def test_old_end_request_cannot_authorize_current_turn() -> None:
    from app.agent.tools import has_explicit_end_request
    context = LLMContext(messages=[
        {"role": "user", "content": "Tolong akhiri panggilan."},
        {"role": "user", "content": "Saya berubah pikiran, lanjut saja."},
    ])
    assert not has_explicit_end_request(context)
