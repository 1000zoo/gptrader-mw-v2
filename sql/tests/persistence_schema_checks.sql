SELECT
    name
FROM sqlite_master
WHERE type = 'table'
  AND name IN (
      'strategy_definitions',
      'signal_generator_definitions',
      'strategy_evaluations',
      'signal_logs'
  )
ORDER BY name;

SELECT
    name
FROM sqlite_master
WHERE type = 'index'
  AND name IN (
      'idx_strategy_definitions_reg_ymd',
      'idx_signal_generator_definitions_reg_ymd',
      'idx_strategy_evaluations_target_reg_ymd',
      'idx_signal_logs_generator_reg_ymd'
  )
ORDER BY name;
