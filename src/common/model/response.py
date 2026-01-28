from pydantic import BaseModel
from typing import Dict, List, Optional

from src.common.model.base import Meta, OhlcvMeta
from src.common.model.params import IndParams


class GetResponse(BaseModel):
    meta: Meta
    data: List[Dict]


class IndPostResponse(BaseModel):
    meta: Meta
    ohlcvMeta: OhlcvMeta
    params: IndParams
    data: List[Dict]

class GptChatResponse(BaseModel):
    recommend: Dict
    raw_content:str
    finish_reason: str
    refusal: Optional[str]
    model: str
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int
    reasoning_tokens: int
    rejected_prediction_tokens: int

class GptResponse(BaseModel):
    meta: Meta
    gptChatResponse: GptChatResponse
