from collections.abc import Callable, Mapping

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
            content = response.get("content")
            if isinstance(content, str) and content:
                return content

        raise LLMClientError("LLM response did not include text content")
