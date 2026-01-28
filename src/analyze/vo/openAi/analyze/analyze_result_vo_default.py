from typing import Optional

from src.common.model.base import Vo


class DefaultAnalyzeResultVo(Vo):
    id: Optional[int] = None

    batch_id: Optional[str] = None
    prompt_id: Optional[str] = None
    symbol_id: Optional[str] = None

    raw_content: Optional[str] = None   # TEXT
    model: Optional[str] = None

    refusal: Optional[str] = None
    finish_reason: Optional[str] = None   # ⚠️ DB 컬럼명 그대로 사용 (finish 오타)

    total_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    rejected_prediction_tokens: Optional[int] = None

    latency_ms: Optional[int] = None

    reg_ymd: Optional[str] = None  # '20251225'

    class Config:
        from_attributes = True
        extra = "ignore"