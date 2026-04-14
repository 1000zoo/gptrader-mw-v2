import asyncio

from src.analyze.repository.openAi.analyze.analyze_result_repo import AnalyzeResultRepository
from src.analyze.vo.openAi.analyze.analyze_result_vo_default import DefaultAnalyzeResultVo

def test_insert_result_bulk():
    repo = AnalyzeResultRepository()
    vo = [DefaultAnalyzeResultVo(batch_id='TEST001')]
    asyncio.run(repo.insert_result_bulk(vo))
