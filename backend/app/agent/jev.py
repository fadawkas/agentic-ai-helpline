import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field
from pipecat.processors.aggregators.llm_context import LLMContext

from app.core.config import Settings
from app.safety.engine import SafetyState

logger = logging.getLogger(__name__)


class AgentPersonality(StrEnum):
    NEUTRAL = "NEUTRAL"
    EMPATHETIC_LISTENER = "EMPATHETIC_LISTENER"
    GENTLE_GUIDE = "GENTLE_GUIDE"
    INFORMATIONAL = "INFORMATIONAL"
    REFERRAL_SUPPORT = "REFERRAL_SUPPORT"


class UserIntent(StrEnum):
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
    EMOTIONAL_SUPPORT = "EMOTIONAL_SUPPORT"
    GUIDANCE = "GUIDANCE"
    INFORMATION = "INFORMATION"
    REFERRAL = "REFERRAL"


class ReasoningCode(StrEnum):
    WARMUP = "WARMUP"
    EXPLICIT_REQUEST = "EXPLICIT_REQUEST"
    EXPRESSED_NEED = "EXPRESSED_NEED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INVALID_RECOMMENDATION = "INVALID_RECOMMENDATION"
    SAFETY_OVERRIDE = "SAFETY_OVERRIDE"


class JevClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personality: AgentPersonality
    intent: UserIntent
    confidence: float = Field(ge=0, le=1)
    reasoning_code: ReasoningCode


@dataclass(frozen=True)
class JevDecision:
    personality: AgentPersonality
    intent: UserIntent
    confidence: float
    reasoning_code: ReasoningCode
    user_turn: int


@dataclass(frozen=True)
class PersonalityConfig:
    version: str
    instruction: str
    allowed_tools: tuple[str, ...]


PERSONALITIES: dict[AgentPersonality, PersonalityConfig] = {
    AgentPersonality.NEUTRAL: PersonalityConfig(
        "1.1", "Hadir dengan hangat dan alami. Tanggapi kebutuhan yang benar-benar diungkapkan; jangan otomatis memberi FAQ atau saran. Jika maksudnya belum jelas, tanyakan satu hal dengan lembut.", ("skip_turn", "end_call")
    ),
    AgentPersonality.EMPATHETIC_LISTENER: PersonalityConfig(
        "1.1", "Utamakan menemani dan memahami. Akui perasaan yang memang disampaikan tanpa menebak atau memakai empati klise; ajukan satu pertanyaan lembut bila berguna. Jangan memberi daftar saran atau mencari materi kecuali diminta atau diperlukan untuk menjawab fakta.", ("skip_turn", "end_call")
    ),
    AgentPersonality.GENTLE_GUIDE: PersonalityConfig(
        "1.1", "Dengarkan situasinya, lalu bila sesuai tawarkan satu langkah kecil yang relevan dan opsional. Gunakan sumber terverifikasi untuk memastikan klaim, tetapi rangkum alami; jangan membacakan kutipan atau daftar materi. Jangan memaksa atau mendiagnosis.", ("skip_turn", "end_call")
    ),
    AgentPersonality.INFORMATIONAL: PersonalityConfig(
        "1.1", "Berikan informasi faktual yang diminta dengan ringkas dan bahasa percakapan. Sintesis sumber menjadi jawaban yang relevan, bukan membacakan hasil retrieval. Akui jika bukti tidak tersedia; jangan mengarang.", ("skip_turn", "end_call")
    ),
    AgentPersonality.REFERRAL_SUPPORT: PersonalityConfig(
        "1.1", "Dukung pilihan mencari bantuan profesional dengan hangat dan tanpa menekan. Bagikan hanya rujukan yang terverifikasi, jangan membacakan daftar panjang, dan jangan mengarang nama atau kontak.", ("skip_turn", "end_call")
    ),
}

_EXPLICIT_ROUTING_PHRASES = (
    "beri saran",
    "tolong arahkan",
    "apa yang harus saya lakukan",
    "informasi tentang",
    "cari bantuan profesional",
    "rekomendasi psikolog",
    "bicara dengan profesional",
    "give me advice",
    "what should i do",
    "find professional help",
)


def latest_user_text(context: LLMContext) -> str:
    for message in reversed(context.get_messages()):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""


def user_turn_count(context: LLMContext) -> int:
    return sum(
        isinstance(message, dict) and message.get("role") == "user"
        for message in context.get_messages()
    )


def has_explicit_routing_request(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(phrase in normalized for phrase in _EXPLICIT_ROUTING_PHRASES)


class JevRouter:
    def __init__(self, settings: Settings, client: Any | None = None):
        if settings.openrouter_api_key is None:
            raise ValueError("OpenRouter key is required for Jev classification")
        self._client = client or AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=8.0,
            max_retries=0,
        )
        self._model = settings.llm_classifier_model
        self._warmup_turns = settings.jev_classification_warmup_turns
        self._threshold = settings.jev_confidence_threshold
        self._stability_turns = settings.jev_switch_stability_turns
        self.personality = AgentPersonality(settings.jev_initial_personality)
        self.history: list[JevDecision] = []
        self._candidate: AgentPersonality | None = None
        self._candidate_turns = 0

    async def close(self) -> None:
        await self._client.close()

    async def route(
        self,
        context: LLMContext,
        *,
        turn: int,
        safety_state: SafetyState,
    ) -> JevDecision:
        if safety_state in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}:
            return self._record(
                AgentPersonality.NEUTRAL,
                UserIntent.EMOTIONAL_SUPPORT,
                1.0,
                ReasoningCode.SAFETY_OVERRIDE,
                turn,
            )
        text = latest_user_text(context)
        explicit = has_explicit_routing_request(text)
        if turn < self._warmup_turns and not explicit:
            self.personality = AgentPersonality.NEUTRAL
            return self._record(
                AgentPersonality.NEUTRAL,
                UserIntent.GENERAL_CONVERSATION,
                1.0,
                ReasoningCode.WARMUP,
                turn,
            )
        try:
            classification = await self._classify(context)
        except Exception as error:
            logger.warning("Jev classification failed: %s", type(error).__name__)
            self._candidate = None
            self._candidate_turns = 0
            self.personality = AgentPersonality.NEUTRAL
            return self._record(
                AgentPersonality.NEUTRAL,
                UserIntent.GENERAL_CONVERSATION,
                0.0,
                ReasoningCode.INVALID_RECOMMENDATION,
                turn,
            )

        if classification.confidence < self._threshold:
            self._candidate = None
            self._candidate_turns = 0
            self.personality = AgentPersonality.NEUTRAL
            return self._record(
                AgentPersonality.NEUTRAL,
                classification.intent,
                classification.confidence,
                ReasoningCode.LOW_CONFIDENCE,
                turn,
            )

        proposed = classification.personality
        if explicit and turn < self._warmup_turns:
            self.personality = proposed
            self._candidate = None
            self._candidate_turns = 0
        elif proposed == self.personality:
            self._candidate = None
            self._candidate_turns = 0
        else:
            if self._candidate == proposed:
                self._candidate_turns += 1
            else:
                self._candidate = proposed
                self._candidate_turns = 1
            if self._candidate_turns >= self._stability_turns:
                self.personality = proposed
                self._candidate = None
                self._candidate_turns = 0

        return self._record(
            self.personality,
            classification.intent,
            classification.confidence,
            classification.reasoning_code,
            turn,
        )

    async def _classify(self, context: LLMContext) -> JevClassification:
        messages = [
            message
            for message in context.get_messages()
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
        ][-8:]
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the user's current expressed conversational need, not a "
                        "diagnosis or personality. Respond in Indonesian. Choose a listed "
                        "personality, intent, confidence from 0 to 1, and reasoning code."
                    ),
                },
                *messages,
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "jev_classification",
                    "strict": True,
                    "schema": JevClassification.model_json_schema(),
                },
            },
            temperature=0,
            max_tokens=320,
            extra_body={"reasoning": {"effort": "none"}},
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("Jev returned an empty classification")
        return JevClassification.model_validate_json(content)

    def _record(
        self,
        personality: AgentPersonality,
        intent: UserIntent,
        confidence: float,
        reasoning_code: ReasoningCode,
        turn: int,
    ) -> JevDecision:
        decision = JevDecision(
            personality=personality,
            intent=intent,
            confidence=confidence,
            reasoning_code=reasoning_code,
            user_turn=turn,
        )
        self.history.append(decision)
        del self.history[:-30]
        return decision


def personality_instruction(personality: AgentPersonality) -> str:
    config = PERSONALITIES[personality]
    return (
        f"Konfigurasi gaya percakapan {personality.value} versi {config.version}: "
        f"{config.instruction} Alat yang tersedia: {', '.join(config.allowed_tools)}."
    )
