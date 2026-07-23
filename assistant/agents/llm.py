"""LLM provider abstraction with fallback, streaming, and LLMAgent contract."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

import requests

from assistant.config import Settings
from assistant.utils.logger import get_logger

logger = get_logger(__name__)


class LLMError(RuntimeError):
    """Raised when no LLM provider can return a response."""


@dataclass
class AgentResult:
    """Structured result returned by the LLM Agent execution."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def chat(self, messages: list[dict[str, str]]) -> str:
        """Return a model response for the supplied conversation messages."""

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        yield self.chat(messages)


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible chat-completions endpoints."""

    def __init__(self, settings: Settings, name: str, api_key: str, model: str, base_url: str | None = None) -> None:
        from openai import OpenAI

        self.settings = settings
        self.name = name
        self.model = model
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": settings.http_timeout_seconds,
        }
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def chat(self, messages: list[dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
        )
        content = response.choices[0].message.content
        return content.strip() if content else ""

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is required for OpenAI.")
        super().__init__(settings, "openai", settings.openai_api_key, settings.openai_model)


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openrouter_api_key:
            raise LLMError("OPENROUTER_API_KEY is required for OpenRouter.")
        super().__init__(settings, "openrouter", settings.openrouter_api_key, settings.openrouter_model, settings.openrouter_url)


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is required for Groq.")
        super().__init__(settings, "groq", settings.groq_api_key, settings.groq_model, settings.groq_url)


class LMStudioProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, "lmstudio", settings.lmstudio_api_key, settings.lmstudio_model, settings.lmstudio_url)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is required for Gemini.")
        from google import genai

        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)

    def chat(self, messages: list[dict[str, str]]) -> str:
        prompt = self._messages_to_prompt(messages)
        response = self.client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
        )
        text = getattr(response, "text", None)
        return text.strip() if text else ""

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
        lines = []
        for message in messages:
            role = message["role"].upper()
            lines.append(f"{role}: {message['content']}")
        lines.append("ASSISTANT:")
        return "\n\n".join(lines)


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for Claude.")
        from anthropic import Anthropic

        self.settings = settings
        self.client = Anthropic(api_key=settings.anthropic_api_key)

    def chat(self, messages: list[dict[str, str]]) -> str:
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] in {"user", "assistant"}]
        response = self.client.messages.create(
            model=self.settings.anthropic_model,
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_temperature,
            system="\n\n".join(system_parts),
            messages=chat_messages,
        )
        parts = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.settings.llm_temperature,
                "num_predict": self.settings.llm_max_tokens,
            },
        }
        response = requests.post(
            f"{self.settings.ollama_url}/api/chat",
            json=payload,
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "").strip()

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.settings.llm_temperature,
                "num_predict": self.settings.llm_max_tokens,
            },
        }
        with requests.post(
            f"{self.settings.ollama_url}/api/chat",
            json=payload,
            timeout=self.settings.http_timeout_seconds,
            stream=True,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
                if data.get("error"):
                    raise LLMError(str(data["error"]))
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content


class LLMClient:
    """Facade that selects configured providers, handles fallbacks, and acts as the LLM Agent."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self.providers = self._build_providers(settings)
        if not self.providers:
            raise LLMError("No usable LLM providers are configured.")
        self.logger.info("LLM providers active:\n%s", ", ".join(provider.name for provider in self.providers))

        # ── LLM Agent State ──────────────────────────────────────────────────
        self.active_model: str = getattr(self.providers[0], "model", "default-model")
        self.provider: str = self.providers[0].name
        self.last_prompt: str = ""
        self.last_response: str = ""
        self.token_usage: int = 0
        self.request_count: int = 0

    # ── AgentInterface Contract ──────────────────────────────────────────────

    def supports(self, task: Any) -> bool:
        """Check if action is a supported LLM agent query."""
        supported = {
            "generate", "chat", "summarize", "rewrite", "classify",
            "extract", "reason", "generate_json", "count_tokens",
            "available_models", "switch_model"
        }
        return task.action in supported

    def execute(self, task: Any) -> AgentResult:
        """Execute the task structured inside AgentTask and return AgentResult."""
        action = task.action
        params = task.parameters or {}

        try:
            if action == "generate":
                prompt = params.get("prompt", "")
                sys_prompt = params.get("system_prompt")
                res = self.generate(prompt, sys_prompt)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "chat":
                msgs = params.get("messages", [])
                res = self.chat(msgs)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "summarize":
                text = params.get("text", "")
                res = self.summarize(text)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "rewrite":
                text = params.get("text", "")
                tone = params.get("tone", "professional")
                res = self.rewrite(text, tone)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "classify":
                text = params.get("text", "")
                cats = params.get("categories", [])
                res = self.classify(text, cats)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "extract":
                text = params.get("text", "")
                schema = params.get("schema", "")
                res = self.extract(text, schema)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "reason":
                prompt = params.get("prompt", "")
                res = self.reason(prompt)
                return AgentResult(success=True, message=res, data=self.get_state())

            elif action == "generate_json":
                prompt = params.get("prompt", "")
                schema = params.get("schema")
                data_map = self.generate_json(prompt, schema)
                return AgentResult(
                    success=True,
                    message="JSON successfully generated.",
                    data=data_map
                )

            elif action == "count_tokens":
                text = params.get("text", "")
                tokens = self.count_tokens(text)
                return AgentResult(
                    success=True,
                    message=f"Analyzed {tokens} tokens.",
                    data={"tokens": tokens}
                )

            elif action == "available_models":
                models = self.available_models()
                return AgentResult(
                    success=True,
                    message="Available models retrieved.",
                    data={"models": models}
                )

            elif action == "switch_model":
                name = params.get("model", "")
                msg = self.switch_model(name)
                return AgentResult(success=True, message=msg, data=self.get_state())

            else:
                return AgentResult(
                    success=False,
                    message=f"Unsupported action: {action}",
                    error="unsupported_action"
                )

        except LLMError as exc:
            return AgentResult(success=False, message=str(exc), error="provider_unavailable")
        except requests.Timeout as exc:
            return AgentResult(success=False, message=str(exc), error="timeout")
        except ValueError as exc:
            return AgentResult(success=False, message=str(exc), error="invalid_model")
        except ModuleNotFoundError as exc:
            return AgentResult(success=False, message=str(exc), error="missing_dependency")
        except TimeoutError as exc:
            return AgentResult(success=False, message=str(exc), error="timeout")
        except Exception as exc:
            return AgentResult(success=False, message=str(exc), error="unexpected_exception")

    def state(self) -> dict[str, Any]:
        return self.get_state()

    def health(self) -> str:
        return "healthy"

    def reset(self) -> None:
        self.last_prompt = ""
        self.last_response = ""
        self.token_usage = 0
        self.request_count = 0

    # ── LLM Agent APIs ───────────────────────────────────────────────────────

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Helper to generate text completions given system bounds."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        self.last_prompt = prompt
        res = self.chat(messages)
        self.last_response = res
        return res

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Standard chat completions facade implementation."""
        errors: list[str] = []
        for provider in self.providers:
            try:
                response = provider.chat(messages)
                response = response.strip()
                if response:
                    self.logger.info("LLM response provider: %s", provider.name)
                    self.provider = provider.name
                    self.active_model = getattr(provider, "model", self.active_model)
                    self.request_count += 1
                    # rough token estimate calculation
                    text_len = sum(len(m.get("content", "")) for m in messages) + len(response)
                    self.token_usage += text_len // 4
                    return response
                errors.append(f"{provider.name}: empty response")
            except Exception as exc:
                self.logger.warning("Provider %s failed: %s", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
        raise LLMError("All LLM providers failed. " + " | ".join(errors))

    def summarize(self, text: str) -> str:
        return self.generate(f"Summarize the following text:\n\n{text}", "You are a concise summarizer assistant.")

    def rewrite(self, text: str, tone: str = "professional") -> str:
        return self.generate(f"Rewrite the following text in a {tone} tone:\n\n{text}", "You are a professional writing assistant.")

    def classify(self, text: str, categories: list[str]) -> str:
        cats_str = ", ".join(categories)
        prompt = f"Classify the following text into one of these categories: [{cats_str}]. Return ONLY the category name.\n\nText:\n{text}"
        return self.generate(prompt, "You are a precise classifier assistant.")

    def extract(self, text: str, schema: str) -> str:
        prompt = f"Extract information matching schema: {schema} from the following text:\n\n{text}"
        return self.generate(prompt, "You are an information extraction assistant.")

    def reason(self, prompt: str) -> str:
        return self.generate(prompt, "You are an advanced reasoning assistant. Think step by step.")

    def generate_json(self, prompt: str, schema: str | None = None) -> dict[str, Any]:
        sys_bounds = "You are a JSON assistant. Output valid JSON only, no markdown blocks."
        if schema:
            sys_bounds += f" Follow schema: {schema}"
        raw = self.generate(prompt, sys_bounds)
        try:
            # strip possible markdown wraps
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.endswith("```"):
                raw = raw[:-3]
            return json.loads(raw.strip())
        except Exception as exc:
            logger.warning("Failed to parse LLM JSON: %s", exc)
            return {"raw_response": raw, "error": "malformed_response"}

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    def available_models(self) -> list[str]:
        models = []
        for p in self.providers:
            mod = getattr(p, "model", None)
            if mod:
                models.append(f"{p.name}/{mod}")
        return models

    def switch_model(self, model_name: str) -> str:
        """Switch active model name on compatible provider."""
        switched = False
        for p in self.providers:
            if hasattr(p, "model"):
                p.model = model_name
                self.active_model = model_name
                switched = True
        if not switched:
            raise ValueError(f"No provider supported switching to model: {model_name}")
        return f"Successfully switched active model to '{model_name}'."

    def get_state(self) -> dict[str, Any]:
        """Expose metrics to SharedContext."""
        return {
            "model": self.active_model,
            "active_model": self.active_model,
            "provider": self.provider,
            "last_prompt": self.last_prompt,
            "last_response": self.last_response,
            "token_usage": self.token_usage,
            "request_count": self.request_count
        }

    # ── Backward Compatibility Methods ───────────────────────────────────────

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterable[str]:
        errors: list[str] = []
        for provider in self.providers:
            emitted = False
            try:
                for chunk in provider.stream(messages):
                    if not chunk:
                        continue
                    emitted = True
                    yield chunk
                if emitted:
                    self.logger.info("Streaming provider: %s", provider.name)
                    return
                errors.append(f"{provider.name}: empty stream")
            except Exception as exc:
                self.logger.warning("Streaming provider %s failed: %s", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
                if emitted:
                    raise LLMError(
                        "Streaming LLM provider failed after returning a partial response. "
                        + " | ".join(errors)
                    ) from exc
        raise LLMError("All streaming LLM providers failed. " + " | ".join(errors))

    @staticmethod
    def _build_providers(settings: Settings) -> list[LLMProvider]:
        provider_types: dict[str, type[LLMProvider]] = {
            "openai": OpenAIProvider,
            "gemini": GeminiProvider,
            "claude": ClaudeProvider,
            "ollama": OllamaProvider,
            "lmstudio": LMStudioProvider,
            "openrouter": OpenRouterProvider,
            "groq": GroqProvider,
        }
        order = getattr(settings, "ai_provider_priority", None) or (
            [settings.ai_provider] + [p for p in settings.ai_provider_fallback_order if p != settings.ai_provider]
        )
        providers: list[LLMProvider] = []
        logger = get_logger(__name__)
        for name in order:
            provider_type = provider_types.get(name)
            if provider_type is None:
                logger.warning("Skipping unknown LLM provider: %s", name)
                continue
            try:
                providers.append(provider_type(settings))
            except LLMError as exc:
                logger.debug("Skipping provider %s: %s", name, exc)
        return providers
