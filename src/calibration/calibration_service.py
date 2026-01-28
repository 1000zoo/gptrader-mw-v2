from dataclasses import dataclass
from typing import List, Optional

from loguru import logger

from src.calibration.calibration_repo import CalibrationRepository
from src.calibration.service.confidence_calibration.confidence_calibration_service import (
    ConfidenceCalibrationService,
)
from src.calibration.vo.confidence_calibration.default import DefaultConfidenceCalibrationVo


@dataclass
class BucketStat:
    bucket_from: float
    bucket_to: float
    trades: int
    winrate: float
    ev: float
    avg_r: float
    pf: float


class CalibrationService:
    def __init__(self):
        self.repo = CalibrationRepository()
        self.snapshot_service = ConfidenceCalibrationService()

    @staticmethod
    def _bucket_ranges() -> List[tuple[float, float]]:
        return [(i / 10, (i + 1) / 10) for i in range(10)]

    async def compute_bucket_stats(
        self, c_interval: str, symbol_id: Optional[str] = None
    ) -> List[BucketStat]:
        rows = await self.repo.fetch_trade_outcomes(c_interval, symbol_id)
        stats: List[BucketStat] = []
        for bucket_from, bucket_to in self._bucket_ranges():
            bucket_rows = [
                r
                for r in rows
                if r.get("raw_confidence") is not None
                and bucket_from <= float(r.get("raw_confidence")) < bucket_to
            ]
            trades = len(bucket_rows)
            if trades == 0:
                stats.append(BucketStat(bucket_from, bucket_to, 0, 0.0, 0.0, 0.0, 0.0))
                continue
            pnl_values = [float(r.get("pnl_usd") or 0.0) for r in bucket_rows]
            r_values = [float(r.get("r_multiple") or 0.0) for r in bucket_rows]
            wins = sum(1 for pnl in pnl_values if pnl > 0)
            winrate = wins / trades
            avg_r = sum(r_values) / trades if trades else 0.0
            ev = avg_r
            gross_profit = sum(p for p in pnl_values if p > 0)
            gross_loss = abs(sum(p for p in pnl_values if p < 0))
            pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
            stats.append(BucketStat(bucket_from, bucket_to, trades, winrate, ev, avg_r, pf))
        return stats

    @staticmethod
    def calibrate(raw_confidence: Optional[float], stats: List[BucketStat]) -> Optional[float]:
        if raw_confidence is None:
            return None
        for stat in stats:
            if stat.bucket_from <= raw_confidence < stat.bucket_to:
                calibrated = raw_confidence + stat.ev * 0.1
                return max(0.0, min(1.0, calibrated))
        return raw_confidence

    @staticmethod
    def select_dynamic_threshold(stats: List[BucketStat], min_trades: int) -> Optional[float]:
        for stat in stats:
            if stat.trades >= min_trades and stat.ev > 0:
                return stat.bucket_from
        return None

    async def snapshot_calibration(self, c_interval: str, symbol_id: Optional[str] = None) -> None:
        stats = await self.compute_bucket_stats(c_interval, symbol_id)
        for stat in stats:
            vo = DefaultConfidenceCalibrationVo(
                c_interval=c_interval,
                symbol_id=symbol_id,
                window_n_trades=stat.trades,
                bucket_from=stat.bucket_from,
                bucket_to=stat.bucket_to,
                trades=stat.trades,
                winrate=stat.winrate,
                ev=stat.ev,
                avg_r=stat.avg_r,
                pf=stat.pf,
            )
            await self.snapshot_service.create_confidence_calibration(vo)
        logger.info(f"calibration snapshot stored for {c_interval} {symbol_id}")
