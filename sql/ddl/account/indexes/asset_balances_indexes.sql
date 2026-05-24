CREATE INDEX IF NOT EXISTS idx_asset_balances_asset_reg_ymd
    ON asset_balances (asset, reg_ymd, reg_dt);
