import json
from loguru import logger

from openai.types.chat import ChatCompletion

from src.common.model.response import GptChatResponse
from src.common.exception.invalid_response_exception import InvalidResponseException

def chat_to_response(chat: ChatCompletion) -> GptChatResponse:
    try:
        raw_output = chat.choices[0].message.content
    except (AttributeError, IndexError) as e:
        raise InvalidResponseException("Chat completion response is missing message content.") from e
    try:
        recommend = json.loads(raw_output)
    except json.JSONDecodeError as e:
        logger.error(f"response message's format is invalid:: {e}")
        raise InvalidResponseException("Chat completion response is not valid JSON.") from e

    return GptChatResponse(
        recommend=recommend,
        raw_content=raw_output,
        finish_reason=chat.choices[0].finish_reason,
        refusal=chat.choices[0].message.refusal,
        model=chat.model,
        completion_tokens=chat.usage.completion_tokens,
        prompt_tokens=chat.usage.prompt_tokens,
        total_tokens=chat.usage.total_tokens,
        reasoning_tokens=chat.usage.completion_tokens_details.reasoning_tokens,
        rejected_prediction_tokens=chat.usage.completion_tokens_details.rejected_prediction_tokens
    )
