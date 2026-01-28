from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime

class Meta(BaseModel):
    metaTime: datetime
    status: int
    msg: str
    ok: bool

class OhlcvMeta(BaseModel):
    symbol: str
    interval: str = "1h"
    limit: int = 150

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": self.limit
        }

class Vo(BaseModel):
    attr1: Optional[str] = None     # use_yn
    attr2: Optional[str] = None
    attr3: Optional[str] = None
    attr4: Optional[str] = None
    attr5: Optional[str] = None
    attr6: Optional[str] = None
    attr7: Optional[str] = None
    attr8: Optional[str] = None
    attr9: Optional[str] = None
    attr10: Optional[str] = None

    reg_dt: Optional[datetime] = None
    upd_dt: Optional[datetime] = None

class Prompts(BaseModel):
    system_prompt: str
    user_prompt: str
    prompt_set_id: str = "default"