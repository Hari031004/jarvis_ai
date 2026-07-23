"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_float(name: str, default: float) -> float:
    value = _env(name)
    if value is None:
        return default
    return float(value)


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    return int(value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def _env_path(name: str, default: Path) -> Path:
    value = _env(name)
    if value is None:
        return default
    return Path(value).expanduser()


def _env_list(name: str, default: list[str]) -> list[str]:
    value = _env(name)
    if value is None:
        return default
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _env_path_list(name: str, default: list[Path]) -> list[Path]:
    fallback = [str(path) for path in default]
    return [Path(item).expanduser() for item in _env_list(name, fallback)]


DEFAULT_AI_PROVIDER_PRIORITY = ["openai", "gemini", "claude", "openrouter", "groq", "ollama", "lmstudio"]


class Settings(BaseModel):
    """Validated runtime settings for the assistant."""

    assistant_name: str = "JARVIS"
    user_name: str = "Hari"
    data_dir: Path = Path.home() / ".jarvis_assistant"
    log_level: str = "INFO"
    log_file: Path = Path.home() / ".jarvis_assistant" / "assistant.log"
    database_path: Path = Path.home() / ".jarvis_assistant" / "jarvis.db"
    secrets_file: Path = Path.home() / ".jarvis_assistant" / "secrets.enc.json"
    stt_aliases_file: Path = Path.home() / ".jarvis_assistant" / "stt_aliases.json"

    ai_provider: str = "openai"
    ai_provider_fallback_order: list[str] = Field(default_factory=lambda: DEFAULT_AI_PROVIDER_PRIORITY.copy())
    ai_provider_priority: list[str] = Field(default_factory=lambda: DEFAULT_AI_PROVIDER_PRIORITY.copy())
    llm_temperature: float = 0.45
    llm_max_tokens: int = 900
    conversation_max_messages: int = 24
    conversation_timeout_seconds: float = 300.0
    default_ai_mode: str = "natural"
    enable_streaming_responses: bool = True

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-latest"

    openrouter_api_key: str | None = None
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"

    groq_api_key: str | None = None
    groq_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-70b-versatile"

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    lmstudio_url: str = "http://localhost:1234/v1"
    lmstudio_api_key: str = "lm-studio"
    lmstudio_model: str = "local-model"

    # --- TTS Settings ---
    voice_name: str = "en-US-AriaNeural"
    enable_streaming_tts: bool = True
    tts_interrupt_enabled: bool = True
    tts_speed: float = 1.0
    tts_pitch: float = 1.0
    tts_volume: float = 1.0
    tts_queue_enabled: bool = True

    # --- Audio / Microphone ---
    sample_rate: int = 16000
    input_device: int | str | None = None
    output_device: int | str | None = None

    # --- Wake Word ---
    wake_word_enabled: bool = True
    wake_word: str = "hey jarvis"
    wakeword_threshold: float = 0.5
    wake_words: list[str] = Field(default_factory=lambda: ["jarvis", "hey jarvis"])
    enable_wake_word: bool = True
    wake_word_auto_restart: bool = True
    wake_word_restart_delay_seconds: float = 1.0
    wake_word_model_reload_on_failure: bool = True

    # --- Noise / Audio Processing ---
    enable_noise_suppression: bool = True
    noise_gate_multiplier: float = 1.8
    enable_echo_cancellation: bool = False
    echo_cancellation_strength: float = 0.35

    # --- Voice Auth ---
    enable_voice_auth: bool = False
    voice_auth_user: str = "Hari"
    voice_auth_threshold: float = 0.92
    voice_profiles_file: Path = Path.home() / ".jarvis_assistant" / "voice_profiles.json"

    # --- VAD Settings ---
    speech_start_threshold: float = 0.018
    speech_stop_threshold: float = 0.010
    speech_silence_seconds: float = 1.05
    speech_min_seconds: float = 0.45
    speech_max_seconds: float = 24.0
    vad_mode: int = 1
    vad_min_speech_duration_ms: int = 250
    vad_min_silence_duration_ms: int = 800
    vad_threshold: float = 0.5
    vad_use_webrtc: bool = True

    # --- Whisper / STT ---
    whisper_model_size: str = "base.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = "en"
    whisper_model_cache: bool = True
    whisper_enable_streaming: bool = True
    whisper_enable_partial: bool = True
    whisper_partial_interval_seconds: float = 1.5
    whisper_auto_detect_language: bool = True
    whisper_supported_languages: list[str] = Field(default_factory=lambda: ["en", "ta", "hi", "te", "ml", "kn"])
    stt_provider: str = "nvidia"
    nvidia_api_key: str | None = None

    # --- Paths ---
    startup_sound_path: Path | None = None
    screenshots_dir: Path = Path.home() / "Pictures" / "JarvisScreenshots"
    user_workspace_dir: Path = Path.home() / "Desktop" / "JarvisWorkspace"
    search_root_dir: Path = Path.home()
    notes_dir: Path = Path.home() / "Documents" / "JarvisNotes"
    weather_location: str = "Chennai"
    news_region: str = "US"

    # --- Security ---
    enable_power_commands: bool = False
    enable_destructive_system_commands: bool = False
    enable_file_delete: bool = True
    allowed_read_roots: list[Path] = Field(default_factory=lambda: [Path.home()])
    allowed_write_roots: list[Path] = Field(default_factory=lambda: [Path.home()])
    rate_limit_max_events: int = 30
    rate_limit_window_seconds: float = 60.0

    # --- Plugins ---
    enable_plugins: bool = True
    enable_plugin_hot_reload: bool = True
    plugins_dir: Path = Path.home() / ".jarvis_assistant" / "plugins"

    # --- MCP ---
    enable_mcp: bool = False
    mcp_config_file: Path = Path.home() / ".jarvis_assistant" / "mcp_servers.json"

    # --- RAG ---
    enable_rag: bool = True
    rag_chunk_size: int = 1200
    rag_chunk_overlap: int = 180
    rag_top_k: int = 5
    rag_vector_dimensions: int = 256

    # --- Vision ---
    enable_vision: bool = True
    webcam_index: int = 0
    vision_output_dir: Path = Path.home() / "Pictures" / "JarvisVision"
    enable_basic_object_detection: bool = True

    # --- GUI ---
    enable_gui: bool = False
    gui_theme: str = "dark"

    # --- Network ---
    http_timeout_seconds: float = 20.0

    # --- Brain / AI ---
    brain_enable_conversation_state: bool = True
    brain_enable_tool_selection: bool = True
    brain_enable_task_planning: bool = True
    brain_enable_memory_retrieval: bool = True
    brain_enable_context_management: bool = True
    brain_enable_error_recovery: bool = True
    brain_enable_fuzzy_matching: bool = True
    brain_fuzzy_match_threshold: float = 0.75
    brain_enable_command_aliases: bool = True

    @field_validator("ai_provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        provider = value.strip().lower().replace("-", "_")
        aliases = {
            "local": "ollama",
            "open_router": "openrouter",
            "google": "gemini",
            "google_gemini": "gemini",
            "anthropic": "claude",
            "lm_studio": "lmstudio",
        }
        provider = aliases.get(provider, provider)
        allowed = {"openai", "gemini", "claude", "ollama", "lmstudio", "openrouter", "groq"}
        if provider not in allowed:
            raise ValueError(f"AI_PROVIDER must be one of {sorted(allowed)}")
        return provider

    @field_validator("ai_provider_fallback_order", "ai_provider_priority", mode="before")
    @classmethod
    def parse_provider_order(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
        return value

    @field_validator("ai_provider_fallback_order", "ai_provider_priority")
    @classmethod
    def normalize_provider_order(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not value or not value.strip():
                continue
            provider = cls.normalize_provider(value)
            if provider not in normalized:
                normalized.append(provider)
        return normalized or ["openai"]

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("input_device", "output_device", mode="before")
    @classmethod
    def normalize_audio_device(cls, value: Any) -> int | str | None:
        if value in {None, ""}:
            return None
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value

    @field_validator(
        "data_dir",
        "log_file",
        "database_path",
        "secrets_file",
        "screenshots_dir",
        "user_workspace_dir",
        "search_root_dir",
        "notes_dir",
        "voice_profiles_file",
        "plugins_dir",
        "mcp_config_file",
        "vision_output_dir",
        mode="before",
    )
    @classmethod
    def expand_paths(cls, value: Any) -> Path:
        return Path(value).expanduser()

    @field_validator("allowed_read_roots", "allowed_write_roots", mode="before")
    @classmethod
    def expand_path_lists(cls, value: Any) -> list[Path]:
        if isinstance(value, str):
            return [Path(item).expanduser() for item in value.replace(";", ",").split(",") if item.strip()]
        return [Path(item).expanduser() for item in value]

    @field_validator("startup_sound_path", mode="before")
    @classmethod
    def optional_path(cls, value: Any) -> Path | None:
        if value in {None, ""}:
            return None
        return Path(value).expanduser()

    @field_validator("whisper_model_size")
    @classmethod
    def validate_whisper_model(cls, value: str) -> str:
        allowed = {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large", "large-v1", "large-v2", "large-v3"}
        if value not in allowed:
            raise ValueError(f"WHISPER_MODEL_SIZE must be one of {sorted(allowed)}")
        return value

    @field_validator("vad_mode")
    @classmethod
    def validate_vad_mode(cls, value: int) -> int:
        if value not in {0, 1, 2, 3}:
            raise ValueError("VAD_MODE must be 0, 1, 2, or 3")
        return value


def _resolve_env_file(env_file: str | Path) -> Path:
    env_path = Path(env_file)
    if env_path.exists() or env_path.name != ".env":
        return env_path
    example_path = env_path.with_name(".env.example")
    return example_path if example_path.exists() else env_path


def _print_llm_settings(settings: Settings) -> None:
    print("Resolved LLM configuration:")
    print(f"AI_PROVIDER={settings.ai_provider}")
    print(f"AI_PROVIDER_PRIORITY={','.join(settings.ai_provider_priority)}")
    print(f"GROQ_API_KEY exists? {bool(settings.groq_api_key)}")
    print(f"GEMINI_API_KEY exists? {bool(settings.gemini_api_key)}")
    print(f"OPENROUTER_API_KEY exists? {bool(settings.openrouter_api_key)}")


def load_settings(env_file: str | Path = ".env") -> Settings:
    """Load settings from .env and the process environment."""

    load_dotenv(_resolve_env_file(env_file), override=True)
    ai_provider = _env("AI_PROVIDER", "openai") or "openai"
    fallback_order = _env_list("AI_PROVIDER_FALLBACK_ORDER", DEFAULT_AI_PROVIDER_PRIORITY)
    priority_from_env = _env("AI_PROVIDER_PRIORITY")
    ai_provider_priority = (
        _env_list("AI_PROVIDER_PRIORITY", fallback_order)
        if priority_from_env is not None
        else [ai_provider] + [provider for provider in fallback_order if provider != ai_provider]
    )
    startup_sound = _env("STARTUP_SOUND_PATH")
    data_dir = _env_path("DATA_DIR", Path.home() / ".jarvis_assistant")

    settings = Settings(
        assistant_name=_env("ASSISTANT_NAME", "JARVIS") or "JARVIS",
        user_name=_env("USER_NAME", "Hari") or "Hari",
        data_dir=data_dir,
        log_level=_env("LOG_LEVEL", "INFO") or "INFO",
        log_file=_env_path("LOG_FILE", data_dir / "assistant.log"),
        database_path=_env_path("DATABASE_PATH", data_dir / "jarvis.db"),
        secrets_file=_env_path("SECRETS_FILE", data_dir / "secrets.enc.json"),
        ai_provider=ai_provider,
        ai_provider_fallback_order=fallback_order,
        ai_provider_priority=ai_provider_priority,
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.45),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 900),
        conversation_max_messages=_env_int("CONVERSATION_MAX_MESSAGES", 24),
        conversation_timeout_seconds=_env_float("CONVERSATION_TIMEOUT_SECONDS", 300.0),
        default_ai_mode=_env("DEFAULT_AI_MODE", "natural") or "natural",
        enable_streaming_responses=_env_bool("ENABLE_STREAMING_RESPONSES", True),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-1.5-flash") or "gemini-1.5-flash",
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest") or "claude-3-5-sonnet-latest",
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_url=(_env("OPENROUTER_URL", "https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1").rstrip("/"),
        openrouter_model=_env("OPENROUTER_MODEL", "openai/gpt-4o-mini") or "openai/gpt-4o-mini",
        groq_api_key=_env("GROQ_API_KEY"),
        groq_url=(_env("GROQ_URL", "https://api.groq.com/openai/v1") or "https://api.groq.com/openai/v1").rstrip("/"),
        groq_model=_env("GROQ_MODEL", "llama-3.1-70b-versatile") or "llama-3.1-70b-versatile",
        ollama_url=(_env("OLLAMA_URL", "http://localhost:11434") or "http://localhost:11434").rstrip("/"),
        ollama_model=_env("OLLAMA_MODEL", "llama3.1") or "llama3.1",
        lmstudio_url=(_env("LMSTUDIO_URL", "http://localhost:1234/v1") or "http://localhost:1234/v1").rstrip("/"),
        lmstudio_api_key=_env("LMSTUDIO_API_KEY", "lm-studio") or "lm-studio",
        lmstudio_model=_env("LMSTUDIO_MODEL", "local-model") or "local-model",
        voice_name=_env("VOICE_NAME", "en-US-AriaNeural") or "en-US-AriaNeural",
        enable_streaming_tts=_env_bool("ENABLE_STREAMING_TTS", True),
        tts_interrupt_enabled=_env_bool("TTS_INTERRUPT_ENABLED", True),
        tts_speed=_env_float("TTS_SPEED", 1.0),
        tts_pitch=_env_float("TTS_PITCH", 1.0),
        tts_volume=_env_float("TTS_VOLUME", 1.0),
        tts_queue_enabled=_env_bool("TTS_QUEUE_ENABLED", True),
        sample_rate=_env_int("SAMPLE_RATE", 16000),
        input_device=_env("INPUT_DEVICE"),
        output_device=_env("OUTPUT_DEVICE"),
        wake_word_enabled=_env_bool("WAKE_WORD_ENABLED", True),
        wake_word=_env("WAKE_WORD", "hey jarvis") or "hey jarvis",
        wakeword_threshold=_env_float("WAKEWORD_THRESHOLD", 0.5),
        wake_words=_env_list("WAKE_WORDS", ["jarvis", "hey jarvis"]),
        enable_wake_word=_env_bool("ENABLE_WAKE_WORD", True),
        wake_word_auto_restart=_env_bool("WAKE_WORD_AUTO_RESTART", True),
        wake_word_restart_delay_seconds=_env_float("WAKE_WORD_RESTART_DELAY_SECONDS", 1.0),
        wake_word_model_reload_on_failure=_env_bool("WAKE_WORD_MODEL_RELOAD_ON_FAILURE", True),
        enable_noise_suppression=_env_bool("ENABLE_NOISE_SUPPRESSION", True),
        noise_gate_multiplier=_env_float("NOISE_GATE_MULTIPLIER", 1.8),
        enable_echo_cancellation=_env_bool("ENABLE_ECHO_CANCELLATION", False),
        echo_cancellation_strength=_env_float("ECHO_CANCELLATION_STRENGTH", 0.35),
        enable_voice_auth=_env_bool("ENABLE_VOICE_AUTH", False),
        voice_auth_user=_env("VOICE_AUTH_USER", "Hari") or "Hari",
        voice_auth_threshold=_env_float("VOICE_AUTH_THRESHOLD", 0.92),
        voice_profiles_file=_env_path("VOICE_PROFILES_FILE", data_dir / "voice_profiles.json"),
        stt_aliases_file=_env_path("STT_ALIASES_FILE", data_dir / "stt_aliases.json"),
        speech_start_threshold=_env_float("SPEECH_START_THRESHOLD", 0.018),
        speech_stop_threshold=_env_float("SPEECH_STOP_THRESHOLD", 0.010),
        speech_silence_seconds=_env_float("SPEECH_SILENCE_SECONDS", 1.05),
        speech_min_seconds=_env_float("SPEECH_MIN_SECONDS", 0.45),
        speech_max_seconds=_env_float("SPEECH_MAX_SECONDS", 24.0),
        vad_mode=_env_int("VAD_MODE", 1),
        vad_min_speech_duration_ms=_env_int("VAD_MIN_SPEECH_DURATION_MS", 250),
        vad_min_silence_duration_ms=_env_int("VAD_MIN_SILENCE_DURATION_MS", 800),
        vad_threshold=_env_float("VAD_THRESHOLD", 0.5),
        vad_use_webrtc=_env_bool("VAD_USE_WEBRTC", True),
        whisper_model_size=_env("WHISPER_MODEL_SIZE", "base.en") or "base.en",
        whisper_device=_env("WHISPER_DEVICE", "cpu") or "cpu",
        whisper_compute_type=_env("WHISPER_COMPUTE_TYPE", "int8") or "int8",
        whisper_language=_env("WHISPER_LANGUAGE", "en"),
        whisper_model_cache=_env_bool("WHISPER_MODEL_CACHE", True),
        whisper_enable_streaming=_env_bool("WHISPER_ENABLE_STREAMING", True),
        whisper_enable_partial=_env_bool("WHISPER_ENABLE_PARTIAL", True),
        whisper_partial_interval_seconds=_env_float("WHISPER_PARTIAL_INTERVAL_SECONDS", 1.5),
        whisper_auto_detect_language=_env_bool("WHISPER_AUTO_DETECT_LANGUAGE", True),
        whisper_supported_languages=_env_list("WHISPER_SUPPORTED_LANGUAGES", ["en", "ta", "hi", "te", "ml", "kn"]),
        stt_provider=_env("STT_PROVIDER", "nvidia") or "nvidia",
        nvidia_api_key=_env("NVIDIA_API_KEY"),
        startup_sound_path=Path(startup_sound).expanduser() if startup_sound else None,
        screenshots_dir=_env_path("SCREENSHOTS_DIR", Path.home() / "Pictures" / "JarvisScreenshots"),
        user_workspace_dir=_env_path("USER_WORKSPACE_DIR", Path.home() / "Desktop" / "JarvisWorkspace"),
        search_root_dir=_env_path("SEARCH_ROOT_DIR", Path.home()),
        notes_dir=_env_path("NOTES_DIR", Path.home() / "Documents" / "JarvisNotes"),
        weather_location=_env("WEATHER_LOCATION", "Chennai") or "Chennai",
        news_region=_env("NEWS_REGION", "US") or "US",
        enable_power_commands=_env_bool("ENABLE_POWER_COMMANDS", False),
        enable_destructive_system_commands=_env_bool("ENABLE_DESTRUCTIVE_SYSTEM_COMMANDS", False),
        enable_file_delete=_env_bool("ENABLE_FILE_DELETE", True),
        allowed_read_roots=_env_path_list("ALLOWED_READ_ROOTS", [Path.home()]),
        allowed_write_roots=_env_path_list("ALLOWED_WRITE_ROOTS", [Path.home()]),
        rate_limit_max_events=_env_int("RATE_LIMIT_MAX_EVENTS", 30),
        rate_limit_window_seconds=_env_float("RATE_LIMIT_WINDOW_SECONDS", 60.0),
        enable_plugins=_env_bool("ENABLE_PLUGINS", True),
        enable_plugin_hot_reload=_env_bool("ENABLE_PLUGIN_HOT_RELOAD", True),
        plugins_dir=_env_path("PLUGINS_DIR", data_dir / "plugins"),
        enable_mcp=_env_bool("ENABLE_MCP", False),
        mcp_config_file=_env_path("MCP_CONFIG_FILE", data_dir / "mcp_servers.json"),
        enable_rag=_env_bool("ENABLE_RAG", True),
        rag_chunk_size=_env_int("RAG_CHUNK_SIZE", 1200),
        rag_chunk_overlap=_env_int("RAG_CHUNK_OVERLAP", 180),
        rag_top_k=_env_int("RAG_TOP_K", 5),
        rag_vector_dimensions=_env_int("RAG_VECTOR_DIMENSIONS", 256),
        enable_vision=_env_bool("ENABLE_VISION", True),
        webcam_index=_env_int("WEBCAM_INDEX", 0),
        vision_output_dir=_env_path("VISION_OUTPUT_DIR", Path.home() / "Pictures" / "JarvisVision"),
        enable_basic_object_detection=_env_bool("ENABLE_BASIC_OBJECT_DETECTION", True),
        enable_gui=_env_bool("ENABLE_GUI", False),
        gui_theme=_env("GUI_THEME", "dark") or "dark",
        http_timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 20.0),
        brain_enable_conversation_state=_env_bool("BRAIN_ENABLE_CONVERSATION_STATE", True),
        brain_enable_tool_selection=_env_bool("BRAIN_ENABLE_TOOL_SELECTION", True),
        brain_enable_task_planning=_env_bool("BRAIN_ENABLE_TASK_PLANNING", True),
        brain_enable_memory_retrieval=_env_bool("BRAIN_ENABLE_MEMORY_RETRIEVAL", True),
        brain_enable_context_management=_env_bool("BRAIN_ENABLE_CONTEXT_MANAGEMENT", True),
        brain_enable_error_recovery=_env_bool("BRAIN_ENABLE_ERROR_RECOVERY", True),
        brain_enable_fuzzy_matching=_env_bool("BRAIN_ENABLE_FUZZY_MATCHING", True),
        brain_fuzzy_match_threshold=_env_float("BRAIN_FUZZY_MATCH_THRESHOLD", 0.75),
        brain_enable_command_aliases=_env_bool("BRAIN_ENABLE_COMMAND_ALIASES", True),
    )
    _print_llm_settings(settings)
    return settings