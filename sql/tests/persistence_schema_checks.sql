SELECT
    name
FROM sqlite_master
WHERE type = 'table'
  AND name IN (
      'account_snapshots',
      'asset_balances',
      'candles',
      'execution_reports',
      'exposure_limits',
      'generated_signals',
      'indicator_sets',
      'indicator_values',
      'market_snapshot_candles',
      'market_snapshots',
      'order_requests',
      'order_results',
      'position_events',
      'position_sizes',
      'position_sizer_configs',
      'positions',
      'promotion_policies',
      'research_runs',
      'risk_checks',
      'risk_policies',
      'runtime_position_events',
      'runtime_positions',
      'runtime_records',
      'signal_generator_regime_routes',
      'strategy_definitions',
      'signal_generator_definitions',
      'signal_generator_strategy_links',
      'strategy_evaluations',
      'strategy_evaluation_metrics',
      'strategy_lifecycle_runs',
      'strategy_results',
      'signals',
      'signal_reasons',
      'signal_logs',
      'trade_decisions',
      'trade_runs'
  )
ORDER BY name;

SELECT
    name
FROM sqlite_master
WHERE type = 'index'
  AND name IN (
      'idx_account_snapshots_exchange_reg_ymd',
      'idx_asset_balances_asset_reg_ymd',
      'idx_candles_symbol_timeframe_reg_ymd',
      'idx_execution_reports_symbol_reg_ymd',
      'idx_execution_reports_position_reg_ymd',
      'idx_exposure_limits_symbol_reg_ymd',
      'idx_generated_signals_generator_reg_ymd',
      'idx_indicator_sets_symbol_timeframe_reg_ymd',
      'idx_indicator_values_symbol_timeframe_key_reg_ymd',
      'idx_market_snapshot_candles_candle',
      'idx_market_snapshots_symbol_timeframe_reg_ymd',
      'idx_order_requests_symbol_reg_ymd',
      'idx_order_requests_decision_reg_ymd',
      'idx_order_results_client_order_reg_ymd',
      'idx_order_results_exchange_order_reg_ymd',
      'idx_position_events_position_reg_ymd',
      'idx_position_events_symbol_type_reg_ymd',
      'idx_position_sizes_decision_reg_ymd',
      'idx_position_sizer_configs_reg_ymd',
      'idx_positions_symbol_status_reg_ymd',
      'idx_promotion_policies_reg_ymd',
      'idx_research_runs_target_mode_reg_ymd',
      'idx_research_runs_symbol_timeframe_reg_ymd',
      'idx_risk_checks_allowed_reason_reg_ymd',
      'idx_risk_policies_reg_ymd',
      'idx_runtime_position_events_position_reg_ymd',
      'idx_runtime_positions_symbol_status_reg_ymd',
      'idx_runtime_records_type_reg_ymd',
      'idx_signal_generator_regime_routes_generator',
      'idx_strategy_definitions_reg_ymd',
      'idx_signal_generator_definitions_reg_ymd',
      'idx_signal_generator_strategy_links_strategy',
      'idx_strategy_evaluations_target_reg_ymd',
      'idx_strategy_evaluation_metrics_name_reg_ymd',
      'idx_strategy_lifecycle_runs_target_type_reg_ymd',
      'idx_strategy_lifecycle_runs_evaluations',
      'idx_strategy_results_strategy_name_reg_ymd',
      'idx_strategy_results_generated_signal',
      'idx_signals_direction_reg_ymd',
      'idx_signal_reasons_code_reg_ymd',
      'idx_signal_logs_generator_reg_ymd',
      'idx_trade_decisions_action_reg_ymd',
      'idx_trade_runs_generator_status_reg_ymd',
      'idx_trade_runs_symbol_timeframe_reg_ymd'
  )
ORDER BY name;

WITH expected_tables(name) AS (
    VALUES
        ('account_snapshots'),
        ('asset_balances'),
        ('candles'),
        ('execution_reports'),
        ('exposure_limits'),
        ('generated_signals'),
        ('indicator_sets'),
        ('indicator_values'),
        ('market_snapshot_candles'),
        ('market_snapshots'),
        ('order_requests'),
        ('order_results'),
        ('position_events'),
        ('position_sizes'),
        ('position_sizer_configs'),
        ('positions'),
        ('promotion_policies'),
        ('research_runs'),
        ('risk_checks'),
        ('risk_policies'),
        ('runtime_position_events'),
        ('runtime_positions'),
        ('runtime_records'),
        ('signal_generator_regime_routes'),
        ('strategy_definitions'),
        ('signal_generator_definitions'),
        ('signal_generator_strategy_links'),
        ('strategy_evaluations'),
        ('strategy_evaluation_metrics'),
        ('strategy_lifecycle_runs'),
        ('strategy_results'),
        ('signals'),
        ('signal_reasons'),
        ('signal_logs'),
        ('trade_decisions'),
        ('trade_runs')
)
SELECT
    'missing_table' AS issue,
    expected_tables.name AS object_name
FROM expected_tables
LEFT JOIN sqlite_master
  ON sqlite_master.type = 'table'
 AND sqlite_master.name = expected_tables.name
WHERE sqlite_master.name IS NULL
ORDER BY object_name;

WITH expected_indexes(name) AS (
    VALUES
        ('idx_account_snapshots_exchange_reg_ymd'),
        ('idx_asset_balances_asset_reg_ymd'),
        ('idx_candles_symbol_timeframe_reg_ymd'),
        ('idx_execution_reports_symbol_reg_ymd'),
        ('idx_execution_reports_position_reg_ymd'),
        ('idx_exposure_limits_symbol_reg_ymd'),
        ('idx_generated_signals_generator_reg_ymd'),
        ('idx_indicator_sets_symbol_timeframe_reg_ymd'),
        ('idx_indicator_values_symbol_timeframe_key_reg_ymd'),
        ('idx_market_snapshot_candles_candle'),
        ('idx_market_snapshots_symbol_timeframe_reg_ymd'),
        ('idx_order_requests_symbol_reg_ymd'),
        ('idx_order_requests_decision_reg_ymd'),
        ('idx_order_results_client_order_reg_ymd'),
        ('idx_order_results_exchange_order_reg_ymd'),
        ('idx_position_events_position_reg_ymd'),
        ('idx_position_events_symbol_type_reg_ymd'),
        ('idx_position_sizes_decision_reg_ymd'),
        ('idx_position_sizer_configs_reg_ymd'),
        ('idx_positions_symbol_status_reg_ymd'),
        ('idx_promotion_policies_reg_ymd'),
        ('idx_research_runs_target_mode_reg_ymd'),
        ('idx_research_runs_symbol_timeframe_reg_ymd'),
        ('idx_risk_checks_allowed_reason_reg_ymd'),
        ('idx_risk_policies_reg_ymd'),
        ('idx_runtime_position_events_position_reg_ymd'),
        ('idx_runtime_positions_symbol_status_reg_ymd'),
        ('idx_runtime_records_type_reg_ymd'),
        ('idx_signal_generator_regime_routes_generator'),
        ('idx_strategy_definitions_reg_ymd'),
        ('idx_signal_generator_definitions_reg_ymd'),
        ('idx_signal_generator_strategy_links_strategy'),
        ('idx_strategy_evaluations_target_reg_ymd'),
        ('idx_strategy_evaluation_metrics_name_reg_ymd'),
        ('idx_strategy_lifecycle_runs_target_type_reg_ymd'),
        ('idx_strategy_lifecycle_runs_evaluations'),
        ('idx_strategy_results_strategy_name_reg_ymd'),
        ('idx_strategy_results_generated_signal'),
        ('idx_signals_direction_reg_ymd'),
        ('idx_signal_reasons_code_reg_ymd'),
        ('idx_signal_logs_generator_reg_ymd'),
        ('idx_trade_decisions_action_reg_ymd'),
        ('idx_trade_runs_symbol_timeframe_reg_ymd'),
        ('idx_trade_runs_generator_status_reg_ymd')
)
SELECT
    'missing_index' AS issue,
    expected_indexes.name AS object_name
FROM expected_indexes
LEFT JOIN sqlite_master
  ON sqlite_master.type = 'index'
 AND sqlite_master.name = expected_indexes.name
WHERE sqlite_master.name IS NULL
ORDER BY object_name;

WITH expected_common_columns(table_name, column_name) AS (
    SELECT name, 'reg_ymd' FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
    UNION ALL
    SELECT name, 'reg_dt' FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
    UNION ALL
    SELECT name, 'upd_dt' FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
    UNION ALL
    SELECT name, 'use_yn' FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
)
SELECT
    'missing_common_column' AS issue,
    expected_common_columns.table_name || '.' || expected_common_columns.column_name AS object_name
FROM expected_common_columns
WHERE NOT EXISTS (
    SELECT 1
    FROM pragma_table_info(expected_common_columns.table_name) AS table_info
    WHERE table_info.name = expected_common_columns.column_name
)
ORDER BY object_name;

SELECT
    'nullable_text_primary_key' AS issue,
    sqlite_master.name || '.' || table_info.name AS object_name
FROM sqlite_master, pragma_table_info(sqlite_master.name) AS table_info
WHERE sqlite_master.type = 'table'
  AND sqlite_master.name NOT LIKE 'sqlite_%'
  AND table_info.pk > 0
  AND upper(table_info.type) = 'TEXT'
  AND table_info."notnull" = 0
ORDER BY object_name;

SELECT
    'missing_use_yn_default' AS issue,
    sqlite_master.name || '.use_yn' AS object_name
FROM sqlite_master, pragma_table_info(sqlite_master.name) AS table_info
WHERE sqlite_master.type = 'table'
  AND sqlite_master.name NOT LIKE 'sqlite_%'
  AND table_info.name = 'use_yn'
  AND coalesce(table_info.dflt_value, '') <> '''Y'''
ORDER BY object_name;

SELECT
    'missing_use_yn_check' AS issue,
    name AS object_name
FROM sqlite_master
WHERE type = 'table'
  AND name NOT LIKE 'sqlite_%'
  AND sql NOT LIKE '%CHECK (use_yn IN (''Y'', ''N''))%'
ORDER BY object_name;

SELECT
    'missing_foreign_key' AS issue,
    sqlite_master.name AS object_name
FROM sqlite_master
WHERE sqlite_master.type = 'table'
  AND sqlite_master.name NOT LIKE 'sqlite_%'
  AND sqlite_master.sql LIKE '%FOREIGN KEY%'
  AND NOT EXISTS (
      SELECT 1
      FROM pragma_foreign_key_list(sqlite_master.name)
  )
ORDER BY object_name;

SELECT
    'index_missing_columns' AS issue,
    index_list.name AS object_name
FROM sqlite_master, pragma_index_list(sqlite_master.name) AS index_list
WHERE sqlite_master.type = 'table'
  AND sqlite_master.name NOT LIKE 'sqlite_%'
  AND index_list.origin = 'c'
  AND NOT EXISTS (
      SELECT 1
      FROM pragma_index_info(index_list.name)
  )
ORDER BY object_name;
