from typing import Optional

from src.common.model.base import Vo


class DefaultSlackSettingVo(Vo):
    id: Optional[int] = None
    process_name: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    is_active: Optional[str] = None

    class Config:
        from_attributes = True
        extra = "ignore"
