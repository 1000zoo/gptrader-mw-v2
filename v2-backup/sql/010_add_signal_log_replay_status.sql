ALTER TABLE signal_log
ADD COLUMN IF NOT EXISTS replay_status VARCHAR(20);

commit;
