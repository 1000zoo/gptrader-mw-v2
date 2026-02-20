import json
from typing import Any, Mapping, List, Tuple
from sqlalchemy import text

from src.common.db.connection import SessionLocal
from src.common.model.base import Vo

ALLOWED_TABLES = {
    'indicators',
    'analyze_result',
    'analyze_action',
    'position_event',
    'symbols',
    'job_run',
    'job_run_hist',
    'ohlcv',
    'indicator_parameter',
    'signal_log',
    'trade_fill',
    'system_state',
    'confidence_calibration',
    'backtest_result',
    'execution_anomaly',
    'slack_setting',
    'regime_state',
    'strategy',
}

def strip_none(d: Mapping[str, Any],) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}

def normalize_params(d: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            normalized[k] = json.dumps(v)
        else:
            normalized[k] = v
    return normalized


def build_insert_sql(table: str, data: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    if table.lower() not in ALLOWED_TABLES:
        raise ValueError(f"table not allowed: {table}")

    clean = strip_none(data)

    if not clean:
        raise ValueError(f"insert data is empty. table: {table}")
    
    cols = ", ".join(clean.keys())
    params = ", ".join(f":{k}" for k in clean.keys())
    sql = text(f"INSERT INTO {table} ({cols}) VALUES ({params})")
    return sql, normalize_params(clean)

def build_select_sql(table: str, condition: Mapping[str, Any]) -> Tuple[Any, dict[str, Any]]:
    if table.lower() not in ALLOWED_TABLES:
        raise ValueError(f"table not allowed: {table}")

    clean = strip_none(condition)

    if clean:
        clauses = [f"{k} = :{k}" for k in clean.keys()]
        where = " WHERE " + " AND ".join(clauses)
    else:
        where = " LIMIT 10"

    sql = text(f"SELECT * FROM {table}{where}")
    return sql, clean

async def common_insert(table: str, row: dict[str, Any]):
    sql, params = build_insert_sql(table, row)
    async with SessionLocal() as session:
        result = await session.execute(sql, params)
        await session.commit()
        return result.rowcount
   
async def common_select(table: str, vo: Vo, vo_cls):
    condition = vo.model_dump(exclude_none=True)
    sql, params = build_select_sql(table, condition)

    async with SessionLocal() as session:
        result = await session.execute(sql, params)
        rows = result.mappings().all()
        return [vo_cls(**r) for r in rows]
    
async def common_insert_bulk(table: str, rows: List[Vo]):
    if not rows:
        return 0
    data_list = [normalize_params(row.model_dump(exclude_none=True)) for row in rows]
    
    sql, _ = build_insert_sql(table, data_list[0])

    async with SessionLocal() as session:
        result = await session.execute(sql, data_list)
        await session.commit()
        return result.rowcount
