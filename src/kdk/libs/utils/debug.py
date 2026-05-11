"""Debug-log helpers."""

import json
import logging

logger = logging.getLogger("kdk.utils.debug")
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
logger.propagate = True


def prettyprint(obj) -> None:
    """
    JSON pretty print for debug logs:
    - Stable key order
    - UTF-8 output with replacement for invalid bytes
    - Safe for dict/list/str/bytes/None
    """
    try:
        if isinstance(obj, (bytes, bytearray)):
            obj = obj.decode("utf-8", "replace")
        text = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)
    except Exception:
        try:
            text = repr(obj)
        except Exception:
            text = "<unprintable>"
    logger.debug(text)
