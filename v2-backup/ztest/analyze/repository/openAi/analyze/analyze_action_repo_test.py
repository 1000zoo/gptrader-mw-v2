import asyncio

from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.analyze.repository.openAi.analyze.analyze_action_repo import AnalyzeActionRepository


def test_insert_action():
    repo = AnalyzeActionRepository()
    vos = [DefaultAnalyzeActionVo(batch_id="TESTBTCUSDT"), DefaultAnalyzeActionVo(batch_id="TESTXRPUSDT")]
    asyncio.run(repo.insert_action_bulk(vos))
