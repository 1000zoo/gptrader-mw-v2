from src.analyze.api.openAi.prompt_manager.prompt_manager import PromptManager
from src.analyze.api.openAi.prompt_manager.impl.base_prompt_manager import BasePromptManager


def get_prompt_manager(**prompt_settings) -> PromptManager:
    return BasePromptManager(**prompt_settings)