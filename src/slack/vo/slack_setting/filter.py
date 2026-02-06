from typing import Optional

from src.common.model.base import Vo


class SlackSettingFilterVo(Vo):
    id: Optional[int] = None
    process_name: Optional[str] = None
    channel_name: Optional[str] = None
    is_active: Optional[bool] = None
