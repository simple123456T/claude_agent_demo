import logging
from functools import lru_cache
from typing import Protocol

import httpx
import openai
from openai import OpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ModelNotConfigured(Exception):
    """MODEL_BASE_URL / MODEL_NAME are not set."""


class ModelUnavailable(Exception):
    """The model endpoint could not be reached or returned an unusable response."""


class ChatClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


class OpenAICompatibleClient:
    """Talks to an in-network OpenAI-compatible endpoint (DeepSeek, Qwen via vLLM, ...)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60.0,
        json_mode: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._json_mode = json_mode
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or "not-required",
            timeout=timeout,
            max_retries=1,
            http_client=http_client,
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        request = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1500,
        }
        try:
            try:
                if self._json_mode:
                    response = self._client.chat.completions.create(
                        **request, response_format={"type": "json_object"}
                    )
                else:
                    response = self._client.chat.completions.create(**request)
            except openai.BadRequestError as exc:
                # Some self-hosted servers do not implement JSON mode; retry in plain mode.
                if not self._json_mode or "response_format" not in str(exc).lower():
                    raise
                logger.warning("Model endpoint rejected response_format; retrying without it")
                response = self._client.chat.completions.create(**request)
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise ModelUnavailable("无法连接模型服务") from exc
        except openai.APIStatusError as exc:
            logger.warning("Model endpoint returned HTTP %s", exc.status_code)
            raise ModelUnavailable(f"模型服务返回错误（HTTP {exc.status_code}）") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            raise ModelUnavailable("模型返回了空内容")
        return content


def build_chat_client(settings: Settings) -> ChatClient:
    if not settings.model_configured:
        raise ModelNotConfigured("尚未配置内网模型（MODEL_BASE_URL、MODEL_NAME）")
    return _cached_client(
        settings.model_base_url or "",
        settings.model_api_key.get_secret_value() if settings.model_api_key else None,
        settings.model_name or "",
        settings.model_timeout_seconds,
        settings.model_json_mode,
    )


@lru_cache
def _cached_client(
    base_url: str, api_key: str | None, model: str, timeout: float, json_mode: bool
) -> ChatClient:
    return OpenAICompatibleClient(
        base_url=base_url, api_key=api_key, model=model, timeout=timeout, json_mode=json_mode
    )
