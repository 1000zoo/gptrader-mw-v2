from typing import Any, Dict, Optional

from src.common.model.base import Vo


class DefaultStrategyVo(Vo):
    id: Optional[int] = None
    strategy_name: Optional[str] = None
    module_path: Optional[str] = None
    module_name: Optional[str] = None
    use_yn: Optional[str] = None

    description: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    version: Optional[str] = None
    priority: Optional[int] = None

    class Config:
        from_attributes = True
        extra = "ignore"
