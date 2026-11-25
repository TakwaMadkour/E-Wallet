import json, logging, uuid
from contextvars import ContextVar

correlation_id_var = ContextVar("correlation_id", default=None)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"timestamp": self.formatTime(record), "level": record.levelname,
                   "logger": record.name, "event": getattr(record, "event", record.getMessage()),
                   "correlation_id": correlation_id_var.get()}
        for key in ("transaction_id", "wallet_id", "user_id", "result_code", "operation"):
            if hasattr(record, key): payload[key] = getattr(record, key)
        if record.exc_info: payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)

logger = logging.getLogger("ewallet")
if not logger.handlers:
    handler = logging.StreamHandler(); handler.setFormatter(JsonFormatter())
    logger.addHandler(handler); logger.setLevel(logging.INFO)

def new_correlation_id():
    value = str(uuid.uuid4()); correlation_id_var.set(value); return value

def log_event(event, **fields):
    logger.info(event, extra={"event": event, **fields})
