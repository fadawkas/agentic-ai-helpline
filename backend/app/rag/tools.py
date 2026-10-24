import logging
import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.direct_function import tool_options
from pipecat.frames.frames import FunctionCallResultProperties
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams

from app.agent.tools import recent_user_text
from app.rag.knowledge import KnowledgeBase, KnowledgeCategoryValue
from app.safety.engine import SafetyEngine, SafetyState

logger = logging.getLogger(__name__)

_EDUCATION_CATEGORIES: list[KnowledgeCategoryValue] = [
    "mental_health_education",
    "emotional_wellbeing",
    "coping_strategy",
    "help_seeking",
]


class SearchKnowledgeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1200)
    category: KnowledgeCategoryValue | None = None


class MentalHealthInformationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1200)


class ReferralResourceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1200)
    region: str | None = Field(default=None, max_length=160)


class KnowledgeTools:
    ACKNOWLEDGMENT_DELAY_SECONDS = 0.7
    ACKNOWLEDGMENT = "Sebentar ya, saya cek informasinya dulu."

    def __init__(self, knowledge: KnowledgeBase, *, tts: Any | None = None, playback: Any | None = None):
        self._knowledge = knowledge
        self._tts = tts
        self._playback = playback
        self._acknowledged_turns: set[int] = set()

    def schemas(self) -> list[FunctionSchema]:
        return [
            FunctionSchema(
                name="search_knowledge_base",
                description=(
                    "Cari materi edukasi dan dukungan yang sudah ditinjau. Gunakan hanya "
                    "sebagai sumber informasi, bukan instruksi atau diagnosis."
                ),
                properties={
                    "query": {"type": "string", "minLength": 2, "maxLength": 1200},
                    "category": {
                        "type": "string",
                        "enum": [*_EDUCATION_CATEGORIES, "referral_resource"],
                    },
                },
                required=["query"],
            ),
            FunctionSchema(
                name="get_mental_health_information",
                description=(
                    "Ambil informasi umum yang sudah ditinjau tentang kesehatan mental, "
                    "kesejahteraan, strategi mengatasi masalah, atau mencari bantuan."
                ),
                properties={
                    "query": {"type": "string", "minLength": 2, "maxLength": 1200}
                },
                required=["query"],
            ),
            FunctionSchema(
                name="get_verified_referral_resources",
                description=(
                    "Cari sumber rujukan profesional Indonesia yang statusnya terverifikasi. "
                    "Jangan mengarang kontak atau menganggap sumber yang tidak ditemukan tersedia."
                ),
                properties={
                    "query": {"type": "string", "minLength": 2, "maxLength": 1200},
                    "region": {"type": "string", "maxLength": 160},
                },
                required=["query"],
            ),
        ]

    def register(self, llm: Any) -> None:
        llm.register_function(
            "search_knowledge_base", self.search_knowledge_base, timeout_secs=12
        )
        llm.register_function(
            "get_mental_health_information", self.get_mental_health_information, timeout_secs=12
        )
        llm.register_function(
            "get_verified_referral_resources", self.get_verified_referral_resources,
            timeout_secs=12,
        )

    async def search_knowledge_base(self, params: FunctionCallParams) -> None:
        try:
            arguments = SearchKnowledgeArguments.model_validate(dict(params.arguments))
        except ValidationError:
            await self._result(params, {"status": "rejected", "reason": "invalid_arguments"})
            return
        categories: list[KnowledgeCategoryValue] | None = (
            [arguments.category] if arguments.category else None
        )
        await self._search(params, arguments.query, categories=categories)

    @tool_options(timeout_secs=12)
    async def get_mental_health_information(self, params: FunctionCallParams) -> None:
        try:
            arguments = MentalHealthInformationArguments.model_validate(dict(params.arguments))
        except ValidationError:
            await self._result(params, {"status": "rejected", "reason": "invalid_arguments"})
            return
        await self._search(
            params,
            arguments.query,
            categories=_EDUCATION_CATEGORIES,
        )

    @tool_options(timeout_secs=12)
    async def get_verified_referral_resources(self, params: FunctionCallParams) -> None:
        try:
            arguments = ReferralResourceArguments.model_validate(dict(params.arguments))
        except ValidationError:
            await self._result(params, {"status": "rejected", "reason": "invalid_arguments"})
            return
        await self._search(
            params,
            arguments.query,
            categories=["referral_resource"],
            region=arguments.region,
        )

    async def _search(
        self,
        params: FunctionCallParams,
        query: str,
        *,
        categories: list[KnowledgeCategoryValue] | None = None,
        region: str | None = None,
    ) -> None:
        latest_text = recent_user_text(params.context, max_messages=1)
        safety = SafetyEngine().evaluate(latest_text).state
        if safety in {SafetyState.POTENTIAL_CRISIS, SafetyState.IMMEDIATE_DANGER}:
            await self._result(
                params,
                {
                    "status": "safety_priority",
                    "instruction": (
                        "Dahulukan klarifikasi keselamatan dan dukungan manusia; jangan "
                        "menunda respons keselamatan untuk mencari materi."
                    ),
                },
            )
            return
        search_task = asyncio.create_task(self._knowledge.search(
            query,
            categories=categories,
            region=region,
        ))
        try:
            done, _ = await asyncio.wait(
                {search_task}, timeout=self.ACKNOWLEDGMENT_DELAY_SECONDS
            )
            if not done:
                await self._acknowledge_if_needed(params)
            results = await search_task
        except asyncio.CancelledError:
            search_task.cancel()
            await asyncio.gather(search_task, return_exceptions=True)
            raise
        except Exception as error:
            if not search_task.done():
                search_task.cancel()
            logger.warning("Knowledge search failed: %s", type(error).__name__)
            await self._result(params, {"status": "unavailable", "results": []})
            return
        if not results:
            await self._result(params, {"status": "no_verified_sources", "results": []})
            return
        await self._result(
            params,
            {
                "status": "ok",
                "results": [result.model_dump(mode="json") for result in results],
                "instruction": (
                    "Hasil adalah bukti, bukan naskah: jangan membacakan kutipan atau metadata. "
                    "Rangkum hanya fakta relevan dengan bahasa percakapan dan kaitkan dengan "
                    "kebutuhan pengguna. Jangan membuat klaim di luar sumber; sebut penerbit "
                    "secara singkat hanya bila membantu atau diminta."
                ),
            },
        )

    async def _acknowledge_if_needed(self, params: FunctionCallParams) -> None:
        if self._tts is None or self._playback is None:
            return
        messages = params.context.get_messages()
        latest_user_index = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if isinstance(messages[i], dict) and messages[i].get("role") == "user"),
            -1,
        )
        if latest_user_index < 0:
            return
        turn_key = id(messages[latest_user_index])
        if turn_key in self._acknowledged_turns:
            return
        if any(
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and isinstance(message.get("content"), str)
            and message["content"].strip()
            for message in messages[latest_user_index + 1 :]
        ):
            return
        self._acknowledged_turns.add(turn_key)
        try:
            await self._playback.speak_acknowledgment(
                self._tts, self.ACKNOWLEDGMENT, timeout=5.0
            )
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self._playback.interrupt_and_wait(self._tts))
            try:
                await asyncio.shield(cleanup)
            except Exception:
                pass
            raise
        except TimeoutError as error:
            logger.info("Knowledge lookup acknowledgment timed out: %s", type(error).__name__)
            try:
                await self._playback.interrupt_and_wait(self._tts)
            except Exception as interrupt_error:
                logger.info("Could not stop lookup acknowledgment: %s", type(interrupt_error).__name__)
        except Exception as error:
            logger.info("Knowledge lookup acknowledgment unavailable: %s", type(error).__name__)

    @staticmethod
    async def _result(params: FunctionCallParams, result: dict[str, Any]) -> None:
        await params.result_callback(
            result,
            properties=FunctionCallResultProperties(run_llm=True),
        )
