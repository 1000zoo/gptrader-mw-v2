import os

from loguru import logger
from openai import OpenAI as ai
from openai import OpenAIError

from src.common.model.base import Prompts
from src.common.model.response import GptChatResponse

from src.analyze.api.openAi.openAi_util import chat_to_response
from src.common.exception.external_api_error import ExternalApiError


class OpenAiApi:
    def __init__(self):
        self.API_KEY = os.getenv("OPENAI_API_KEY")
        self.GPT_MODEL = os.getenv("OPENAI_GPT_MODEL")
        self.client = ai(api_key=self.API_KEY)
    
    def chat(self, prompts: Prompts) -> GptChatResponse:
        try:
            response = self.client.chat.completions.create(
                model=self.GPT_MODEL,
                messages=[
                    {"role": "system", "content": prompts.system_prompt},
                    {"role": "user", "content": prompts.user_prompt}
                ],
                max_completion_tokens=10000
            )
            return chat_to_response(response)
            
        except (OpenAIError, ValueError, TypeError) as e:
            logger.error(f"chat error:: {e}")
            raise ExternalApiError("OpenAI chat request failed.") from e
