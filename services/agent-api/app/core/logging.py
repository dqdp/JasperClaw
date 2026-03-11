import json
import logging
import os
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

LOGGER_NAME = "agent_api"


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(level=level, format="%(message)s")
    else:
        root_logger.setLevel(level)
        for handler in root_logger.handlers:
            handler.setFormatter(logging.Formatter("%(message)s"))

    logging.getLogger(LOGGER_NAME).setLevel(level)


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **{key: _serialize(value) for key, value in fields.items()},
    }
    logging.getLogger(LOGGER_NAME).log(
        level,
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )


def _serialize(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    return str(value)
