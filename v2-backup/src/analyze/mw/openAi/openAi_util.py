
from src.common.model.response import GptResponse, GptChatResponse
from src.common.model.base import Meta
from src.common.util.base import success_meta, fail_meta

from loguru import logger

def to_api_response(res: GptChatResponse):
    if not res:
        logger.warning(f"openAi API connection ERROR")
        meta = fail_meta()
        return GptResponse(
            meta=meta,
            gptChatResponse=GptChatResponse(
                recommend={"error": "😅"},
                raw_content="error",
                finsih_reason="error",
                refusal="None",
                model="None",
                completion_tokens=0,
                prompt_tokens=0,
                total_tokens=0,
                reasoning_tokens=0,
                rejected_prediction_tokens=0
            )
        )
    meta = success_meta()
    if "error" in res.recommend:
        logger.warning(f"openai api response format might be invalid {res.recommend}")
        meta = fail_meta()
    return GptResponse(
        meta=meta, gptChatResponse=res
    )