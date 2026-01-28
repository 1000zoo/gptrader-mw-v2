# Quant Stability Layers

This document tracks the new stability-layer foundation for gptrader-mw.

## Step 1: Schema + Skeletons
- Added SQL scripts for signal logging, trade fills, system state, confidence calibration, backtests, and execution anomalies.
- Added repository/service/VO skeletons for the new tables to keep the executor/service/repository/vo pattern consistent.

## Step 2: Signal Logging
- AnalyzeService now creates a signal_log entry after GPT JSON parsing so every decision is recorded.

## Step 3: TradeService Scaffolding
- TradeService now checks system_state before new entries and creates trade_fill records with OPEN status.

## Step 4: Risk Engine + Kill Switch + Ops + Alerts
- Added RiskEngine and kill switch services with Slack alert integration, plus initial ops state/health endpoints.

## Step 5: Calibration + Dynamic Thresholds + Risk Sizing
- Added calibration bucket logic and dynamic thresholds; TradeService now supports risk-based sizing when enabled.

## Step 6: Websocket Reconciliation + Research + Performance
- Websocket handlers now reconcile trade fills and log execution anomalies, with a research replay runner and ops performance endpoint.
