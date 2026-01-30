import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Optional

from loguru import logger
from sqlalchemy import bindparam, text

from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.service.symbol.symbol_service import SymbolService
from src.common.db.connection import SessionLocal
from src.research.service.backtest_result.backtest_result_service import BacktestResultService
from src.research.vo.backtest_result.default import DefaultBacktestResultVo

REPLAY_DONE_STATUS = "REPLAY_DONE"


@dataclass
class ReplayConfig:
    c_interval: str
    symbol_id: Optional[str]
    limit: int
    forward_candles: int


class ResearchRunner:
    def __init__(self):
        self.backtest_service = BacktestResultService()
        self.symbol_service = SymbolService()
        self.ohlcv_service = OhlcvService()

    async def _resolve_symbol_ids(self, config: ReplayConfig) -> list[str]:
        if config.symbol_id:
            return [config.symbol_id]
        symbols = await self.symbol_service.find_use_symbols()
        return [symbol.symbol_id for symbol in symbols if symbol.symbol_id]

    async def _fetch_signal_logs(self, config: ReplayConfig, symbol_ids: list[str]):
        if not symbol_ids:
            return []
        sql = text(
            """
            SELECT * FROM signal_log
            WHERE raw_position != 'WAIT'
              AND (replay_status IS NULL OR replay_status != :replay_status)
              AND symbol_id IN :symbol_ids
              AND c_interval = :c_interval
            ORDER BY base_ts DESC
            LIMIT :limit
            """
        ).bindparams(bindparam("symbol_ids", expanding=True))
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {
                    "symbol_ids": symbol_ids,
                    "c_interval": config.c_interval,
                    "limit": config.limit,
                    "replay_status": REPLAY_DONE_STATUS,
                },
            )
            return result.mappings().all()

    async def _fetch_ohlcv_window(self, symbol_id: str, c_interval: str, base_ts: datetime, limit: int):
        sql = text(
            """
            SELECT * FROM ohlcv
            WHERE symbol_id = :symbol_id
              AND c_interval = :c_interval
              AND ts >= :base_ts
            ORDER BY ts ASC
            LIMIT :limit
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {
                    "symbol_id": symbol_id,
                    "c_interval": c_interval,
                    "base_ts": base_ts,
                    "limit": limit,
                },
            )
            return result.mappings().all()

    async def _ensure_ohlcv_window(self, symbol_id: str, c_interval: str, base_ts: datetime, limit: int):
        candles = await self._fetch_ohlcv_window(symbol_id, c_interval, base_ts, limit)
        if len(candles) >= limit:
            return candles
        batch_id = f"replay-{symbol_id}-{base_ts.strftime('%Y%m%d%H%M%S')}"
        await self.ohlcv_service.load_ohlcv_window(
            symbol_name=symbol_id,
            interval=c_interval,
            limit=limit,
            batch_id=batch_id,
            start_time=base_ts,
        )
        return await self._fetch_ohlcv_window(symbol_id, c_interval, base_ts, limit)

    async def _mark_replay_done(self, signal_ids: list[int]):
        if not signal_ids:
            return
        sql = text(
            """
            UPDATE signal_log
            SET replay_status = :replay_status
            WHERE id IN :signal_ids
            """
        ).bindparams(bindparam("signal_ids", expanding=True))
        async with SessionLocal() as session:
            await session.execute(
                sql,
                {"replay_status": REPLAY_DONE_STATUS, "signal_ids": signal_ids},
            )
            await session.commit()

    @staticmethod
    def _simulate_trade(signal, candles):
        if not candles:
            return None
        entry_price = float(candles[0]["c_close"] or candles[0]["c_open"])
        tp = signal["tp_price"]
        sl = signal["sl_price"]
        side = signal["raw_position"]
        if tp is None or sl is None:
            return None
        for candle in candles[1:]:
            high = float(candle["c_high"])
            low = float(candle["c_low"])
            if side == "LONG":
                if low <= sl:
                    exit_price = sl
                    break
                if high >= tp:
                    exit_price = tp
                    break
            else:
                if high >= sl:
                    exit_price = sl
                    break
                if low <= tp:
                    exit_price = tp
                    break
        else:
            exit_price = float(candles[-1]["c_close"])
        pnl_pct = (exit_price - entry_price) / entry_price
        if side == "SHORT":
            pnl_pct = -pnl_pct
        return pnl_pct

    async def run_replay(self, config: ReplayConfig):
        symbol_ids = await self._resolve_symbol_ids(config)
        signals = await self._fetch_signal_logs(config, symbol_ids)
        returns = []
        processed_signal_ids = []
        for signal in signals:
            candles = await self._ensure_ohlcv_window(
                signal["symbol_id"],
                signal["c_interval"],
                signal["base_ts"],
                config.forward_candles,
            )
            pnl_pct = self._simulate_trade(signal, candles)
            if pnl_pct is not None:
                returns.append(pnl_pct)
            processed_signal_ids.append(signal["id"])
        trades = len(returns)
        winrate = sum(1 for r in returns if r > 0) / trades if trades else 0.0
        pnl_usd = sum(returns)
        sharpe = 0.0
        if trades > 1 and pstdev(returns) > 0:
            sharpe = mean(returns) / pstdev(returns)
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
        config_payload = {
            "prompt_version": None,
            "indicator_params_version": None,
            "flags": {"llm_recall": False},
            "universe": config.symbol_id or "all",
            "timeframe": config.c_interval,
        }
        await self.backtest_service.create_backtest_result(
            DefaultBacktestResultVo(
                config=config_payload,
                period_start=datetime.now(timezone.utc),
                period_end=datetime.now(timezone.utc),
                pnl_usd=pnl_usd,
                sharpe=sharpe,
                pf=pf,
                mdd=0.0,
                trades=trades,
                winrate=winrate,
                turnover=0.0,
            )
        )
        await self._mark_replay_done(processed_signal_ids)
        logger.info(f"research replay stored trades={trades} pnl_usd={pnl_usd}")


async def run_from_env():
    c_interval = os.getenv("RESEARCH_INTERVAL", "1h")
    symbol_id = os.getenv("RESEARCH_SYMBOL")
    limit = int(os.getenv("RESEARCH_LIMIT", "100"))
    forward_candles = int(os.getenv("RESEARCH_FORWARD_CANDLES", "50"))
    runner = ResearchRunner()
    await runner.run_replay(
        ReplayConfig(
            c_interval=c_interval,
            symbol_id=symbol_id,
            limit=limit,
            forward_candles=forward_candles,
        )
    )


def run():
    asyncio.run(run_from_env())
