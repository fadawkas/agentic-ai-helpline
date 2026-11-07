from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "voice-support"
    app_env: str = "development"
    app_debug: bool = True
    postgres_host: str = "postgresql"
    postgres_port: int = 5432
    postgres_user: str = "voice_support"
    postgres_password: SecretStr
    postgres_database: str = "voice_support"
    qdrant_url: str = "http://qdrant:6333"
    telephony_enabled: bool = False
    asterisk_ari_url: str = "http://asterisk:8088/ari"
    asterisk_ari_username: str = "voice_support"
    asterisk_ari_password: SecretStr = SecretStr("")
    asterisk_ari_app: str = "voice-support"
    asterisk_ai_extension: str = "7000"
    asterisk_media_websocket_client: str = "voice_support_media"
    asterisk_media_format: str = "slin16"
    voice_sample_rate: int = 16000
    voice_agent_enabled: bool = False
    deepgram_api_key: SecretStr | None = None
    stt_model: str = "nova-3"
    stt_language: str = "id"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_conversation_model: str = "deepseek/deepseek-v4.1-flash-1017"
    llm_classifier_model: str = "deepseek/deepseek-v4.1-flash-1017"
    llm_max_output_tokens: int = Field(default=1000, ge=1, le=1000)
    conversation_context_max_turns: int = Field(default=30, ge=1, le=30)
    jev_initial_personality: str = "NEUTRAL"
    jev_classification_warmup_turns: int = Field(default=3, ge=1)
    jev_confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    jev_switch_stability_turns: int = Field(default=2, ge=1)
    fish_audio_api_key: SecretStr | None = None
    fish_tts_model: str = "s2.1-pro-free"
    fish_reference_id: str | None = None
    fish_tts_language: str = "id"
    fish_tts_latency: str = "balanced"
    rag_embedding_model: str = "intfloat/multilingual-e5-large"
    rag_embedding_dimensions: int = Field(default=1024, ge=1)
    rag_collection_name: str = "voice_support_knowledge_v1"
    rag_min_similarity: float = Field(default=0.45, ge=0, le=1)
    rag_max_results: int = Field(default=4, ge=1, le=10)
    rag_query_rewrite_enabled: bool = True
    rag_rerank_min_score: float = Field(default=0.4, ge=0, le=1)
    rag_rerank_model: str = "cohere/rerank-4-fast"
    admin_username: str = "admin"
    admin_password: SecretStr | None = None
    admin_session_secret: SecretStr | None = None
    knowledge_storage_path: str = "/app/knowledge/uploads"
    knowledge_max_upload_bytes: int = Field(default=20_000_000, ge=1_000_000)

    model_config = SettingsConfigDict(case_sensitive=False)

    def validate_telephony(self) -> None:
        if not self.asterisk_ari_username.strip() or not self.asterisk_ari_password.get_secret_value().strip():
            raise ValueError("Telephony requires ASTERISK_ARI_USERNAME and ASTERISK_ARI_PASSWORD.")

    def validate_voice_agent(self) -> None:
        required_secrets = {
            "DEEPGRAM_API_KEY": self.deepgram_api_key,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "FISH_AUDIO_API_KEY": self.fish_audio_api_key,
        }
        missing = [
            name
            for name, value in required_secrets.items()
            if value is None or not value.get_secret_value().strip()
        ]
        if not self.fish_reference_id or not self.fish_reference_id.strip():
            missing.append("FISH_REFERENCE_ID")
        if missing:
            raise ValueError(
                "Voice agent is enabled but required configuration is missing: "
                + ", ".join(missing)
            )


settings = Settings()
