import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts":     datetime.now(__import__("datetime").timezone(__import__("datetime").timedelta(hours=-3))).isoformat(),
            "level":  record.levelname,
            "module": record.name,
            "msg":    record.getMessage(),
        }, ensure_ascii=False)

def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
