from datetime import datetime

def reg_ymd_now() -> str:
    return datetime.now().strftime("%Y%m%d")