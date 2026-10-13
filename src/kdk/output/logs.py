"""Engine log routing for the CLI, kept free of rich."""

from __future__ import annotations

import logging


class DedupeFilter(logging.Filter):
    """Log filter passing each distinct message once; a bad include repeats it at every use."""

    def __init__(self):
        super().__init__()
        self._seen = set()

    def filter(self, record):
        """Whether no message with the same logger, level and text has passed yet."""
        key = (record.name, record.levelno, record.getMessage())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def quiet_engine_logging(debug=False):
    """Quiet engine logs below ERROR outside debug, sending the rest to stderr once each."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handler.addFilter(DedupeFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if debug else logging.ERROR)

    # Whatever the engine logs below ERROR is already a reported issue
    logging.getLogger("kdk").setLevel(logging.DEBUG if debug else logging.ERROR)
