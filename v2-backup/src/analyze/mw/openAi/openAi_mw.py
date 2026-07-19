from fastapi import APIRouter, Depends

from src.analyze.api.openAi.openAi_api import OpenAiApi
from src.analyze.api.openAi.prompt_manager.impl.base_prompt_manager import BasePromptManager
from src.common.model.request import AnalyzeRequest
from src.common.model.response import GptResponse
from src.common.model.base import Prompts
from src.analyze.mw.openAi.openAi_util import to_api_response


router = APIRouter(prefix="/analyze")


@router.post("/", response_model=GptResponse)
def analyze(req: AnalyzeRequest, svc = Depends(lambda: AnalyzeService())):
    prompts = svc.prepare_prompts(req)
    return svc.chat(prompts)
    

class AnalyzeService:
    def __init__(self):
        self.openAiApi = OpenAiApi()
        self.pm = BasePromptManager()

    def prepare_prompts(self, req: AnalyzeRequest) -> Prompts:
        return self.pm.generate_from_reqeust(req)
    
    def chat(self, prompts: Prompts) -> GptResponse:
        chatResponse = self.openAiApi.chat(prompts=prompts)
        return to_api_response(chatResponse)
