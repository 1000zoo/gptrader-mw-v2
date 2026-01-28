from typing import Protocol

from typing import Any

from src.common.model.base import Prompts


class PromptManager(Protocol):
    def __init__(self):
        super().__init__()
        self.system_prompt = ""
        self.user_prompt = ""

    def generate_prompts(self, **kwargs) -> Prompts:
        ...

    def generate_from_request(self, req: Any) -> Prompts:
        ...

    def generate_from(self, **kwargs) -> Prompts:
        ...