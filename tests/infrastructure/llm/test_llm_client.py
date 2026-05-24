import pytest

from src.infrastructure.llm.llm_client import LLMClient, LLMClientError
from src.infrastructure.llm.prompt_builder import PromptMessage


class FakeModelClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def __call__(self, *, model, messages, timeout_seconds):
        self.requests.append(
            {
                "model": model,
                "messages": messages,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def test_llm_client_invokes_injected_client_with_plain_messages():
    raw_client = FakeModelClient({"content": '{"direction":"wait"}'})
    messages = (
        PromptMessage(role="system", content="system prompt"),
        PromptMessage(role="user", content="user prompt"),
    )

    result = LLMClient(raw_client).generate(
        model="test-model",
        messages=messages,
        timeout_seconds=10,
    )

    assert result == '{"direction":"wait"}'
    assert raw_client.requests == [
        {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
            "timeout_seconds": 10,
        }
    ]


def test_llm_client_accepts_plain_string_response():
    raw_client = FakeModelClient("plain response")

    result = LLMClient(raw_client).generate(
        model="test-model",
        messages=(PromptMessage(role="user", content="prompt"),),
        timeout_seconds=5,
    )

    assert result == "plain response"


def test_llm_client_extracts_chat_choice_message_content():
    raw_client = FakeModelClient(
        {"choices": [{"message": {"content": '{"direction":"long"}'}}]}
    )

    result = LLMClient(raw_client).generate(
        model="test-model",
        messages=(PromptMessage(role="user", content="prompt"),),
        timeout_seconds=5,
    )

    assert result == '{"direction":"long"}'


def test_llm_client_extracts_response_output_text():
    raw_client = FakeModelClient({"output_text": '{"direction":"short"}'})

    result = LLMClient(raw_client).generate(
        model="test-model",
        messages=(PromptMessage(role="user", content="prompt"),),
        timeout_seconds=5,
    )

    assert result == '{"direction":"short"}'


def test_llm_client_extracts_attribute_text():
    class TextResponse:
        text = '{"direction":"wait"}'

    raw_client = FakeModelClient(TextResponse())

    result = LLMClient(raw_client).generate(
        model="test-model",
        messages=(PromptMessage(role="user", content="prompt"),),
        timeout_seconds=5,
    )

    assert result == '{"direction":"wait"}'


def test_llm_client_translates_low_level_failure():
    def failing_client(*, model, messages, timeout_seconds):
        raise RuntimeError("transport failed")

    with pytest.raises(LLMClientError):
        LLMClient(failing_client).generate(
            model="test-model",
            messages=(PromptMessage(role="user", content="prompt"),),
            timeout_seconds=5,
        )


def test_llm_client_rejects_missing_text():
    raw_client = FakeModelClient({"unexpected": "shape"})

    with pytest.raises(LLMClientError):
        LLMClient(raw_client).generate(
            model="test-model",
            messages=(PromptMessage(role="user", content="prompt"),),
            timeout_seconds=5,
        )
