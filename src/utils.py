In src/utils.py, change:
cfg = get_config().logging
log_dir = Path(cfg.get("log_dir", "logs"))
To:
cfg = get_config().logging
log_dir = Path(cfg.log_dir)
And change:
retention_days = cfg.get("file_retention_days", 7)
To:
retention_days = cfg.file_retention_days
