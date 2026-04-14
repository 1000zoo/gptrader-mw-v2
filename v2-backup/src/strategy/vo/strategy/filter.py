from typing import Optional

from src.common.model.base import Vo


class StrategyFilterVo(Vo):
    id: Optional[int] = None
    strategy_name: Optional[str] = None
    module_path: Optional[str] = None
    module_name: Optional[str] = None
    use_yn: Optional[str] = None
    version: Optional[str] = None
    priority: Optional[int] = None
