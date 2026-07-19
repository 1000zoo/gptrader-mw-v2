from src.common.model.params import IndParams
from src.indicators.vo.indicator_parameter.default import DefaultIndicatorParamsVo
from src.indicators.repository.indicator_parameter.indParam_repo import IndicatorParamRepository
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.repository_error import RepositoryError
from sqlalchemy.exc import SQLAlchemyError

class IndicatorParamService:
    def __init__(self):
        self.repository = IndicatorParamRepository()
        
    async def find_params(self, vo: DefaultIndicatorParamsVo) -> IndParams:
        try:
            params = await self.repository.select_params(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch indicator parameters.") from e
        if not params:
            raise DataNotFoundException("Indicator parameters not found.")
        return params
        
    async def findby_name(self, name: str) -> IndParams:
        params = await self.find_params(DefaultIndicatorParamsVo(name=name))
        return params
