import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import (
    ModelNotConfigured,
    ModelUnavailable,
    OpenAICompatibleClient,
    build_chat_client,
)


def completion(content: str | None) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "qwen",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def client_for(handler, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="http://model.internal/v1",
        api_key=None,
        model="qwen",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


MESSAGES = [{"role": "user", "content": "你好"}]


def test_sends_deterministic_json_mode_request_to_configured_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion('{"status":"ok"}'))

    result = client_for(handler).complete(MESSAGES)

    assert result == '{"status":"ok"}'
    assert seen["url"] == "http://model.internal/v1/chat/completions"
    assert seen["body"]["model"] == "qwen"
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_falls_back_to_plain_mode_when_endpoint_lacks_json_mode():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(
                400, json={"error": {"message": "response_format is not supported"}}
            )
        return httpx.Response(200, json=completion("{}"))

    assert client_for(handler).complete(MESSAGES) == "{}"
    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]


def test_unrelated_bad_request_is_not_retried_as_plain_mode():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "context too long"}})

    with pytest.raises(ModelUnavailable, match="400"):
        client_for(handler).complete(MESSAGES)
    assert len(calls) == 1


def test_connection_failure_becomes_model_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ModelUnavailable, match="无法连接"):
        client_for(handler).complete(MESSAGES)


def test_server_error_becomes_model_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    with pytest.raises(ModelUnavailable, match="500"):
        client_for(handler).complete(MESSAGES)


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_reply_is_unusable(content):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion(content))

    with pytest.raises(ModelUnavailable, match="空内容"):
        client_for(handler).complete(MESSAGES)


def test_unconfigured_model_is_reported_clearly():
    settings = Settings(
        _env_file=None, database_url="postgresql://x/y", redis_url="redis://x/0"
    )

    with pytest.raises(ModelNotConfigured):
        build_chat_client(settings)
