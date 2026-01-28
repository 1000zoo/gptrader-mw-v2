from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class SignalLogFilterVo(Vo):
    id: Optional[int] = None
    run_id: Optional[str] = None
    job_run_id: Optional[str] = None
    symbol_id: Optional[str] = None
    c_interval: Optional[str] = None
    base_ts: Optional[datetime] = None
    prompt_version: Optional[str] = None
    indicator_params_version: Optional[str] = None
