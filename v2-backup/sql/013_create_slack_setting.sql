CREATE TABLE slack_setting (
    id BIGSERIAL PRIMARY KEY,
    process_name VARCHAR(100),
    channel_id 	VARCHAR(100),
    channel_name VARCHAR(100),
    is_active          VARCHAR(1) NOT NULL DEFAULT 'Y',
    attr1           TEXT,
    attr2           TEXT,
    attr3           TEXT,
    attr4           TEXT,
    attr5           TEXT,
    attr6           TEXT,
    attr7           TEXT,
    attr8           TEXT,
    attr9           TEXT,
    attr10          TEXT,
    reg_dt          TIMESTAMPTZ DEFAULT NOW(),
    upd_dt          TIMESTAMPTZ
);

commit;

select * from slack_setting;

insert into slack_setting (
	process_name ,
	channel_id,
	channel_name 
) values (
	'test',
	'C0AP44YUBCP',
	'test'
);

insert into slack_setting (
	process_name ,
	channel_id,
	channel_name 
) values (
	'position_event',
	'C0APYKFQ57B',
	'position_event'
);