from collections.abc import Callable, Mapping, Sequence

from src.infrastructure.llm.prompt_builder import PromptMessage


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, client: Callable[..., object]) -> None:
        self._client = client

    def generate(
        self,
        *,
        model: str,
        messages: tuple[PromptMessage, ...],
        timeout_seconds: int,
    ) -> str:
        try:
            response = self._client(
                model=model,
                messages=[
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                timeout_seconds=timeout_seconds,
            )
            return self._extract_text(response)
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError("LLM request failed") from exc

    def _extract_text(self, response: object) -> str:
        if isinstance(response, str) and response:
            return response

        if isinstance(response, Mapping):
            return self._extract_text_from_mapping(response)

        for attribute_name in ("output_text", "text", "content"):
            value = getattr(response, attribute_name, None)
            if isinstance(value, str) and value:
                return value

        raise LLMClientError("LLM response did not include text content")

    def _extract_text_from_mapping(self, response: Mapping[object, object]) -> str:
        for key in ("content", "output_text", "text"):
            content = response.get(key)
            if isinstance(content, str) and content:
                return content

        choices = response.get("choices")
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)):
            for choice in choices:
                if isinstance(choice, Mapping):
                    message = choice.get("message")
                    if isinstance(message, Mapping):
                        content = message.get("content")
                        if isinstance(content, str) and content:
                            return content
                    content = choice.get("text")
                    if isinstance(content, str) and content:
                        return content

        raise LLMClientError("LLM response did not include text content")
