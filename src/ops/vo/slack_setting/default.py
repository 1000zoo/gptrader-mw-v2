from typing import Optional

from src.common.model.base import Vo


class DefaultSlackSettingVo(Vo):
    id: Optional[int] = None
    process_name: Optional[str] = None
    channel_name: Optional[str] = None
    webhook_url: Optional[str] = None
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True
        extra = "ignore"
