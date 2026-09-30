"""`InfoProvider` facade - combines `LoaderMixin` and `CheckerMixin` into a single public API."""

from __future__ import annotations

from .loader import LoaderMixin
from .checker import CheckerMixin


class InfoProvider(LoaderMixin, CheckerMixin):
    def __init__(self):
        self.addon = None
        self.template_root = None
        self.WINDOW_FILENAMES: list = []
        self.WINDOW_NAMES: list = []
        self.WINDOW_IDS: list = []
        self.MODELESS_IDS: set = set()
        self.DIALOG_IDS: set = set()
        self.OBSOLETE_WINDOW_FILES: dict = {}
        self.INFO_NAMES: dict = {}
        self.builtins: list = []
        self.conditions: list = []
        self.template_attribs: dict = {}
        self.template_values: dict = {}
        self.settings: dict = {}
        self.kodi_path: str | None = None
