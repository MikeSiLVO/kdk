"""Core validation runner shared by CLI and GUI; no UI code here."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable

from .config import load_config, Settings
from .libs.infoprovider.provider import InfoProvider
from .libs.reporting.text import generate_text_report
from .libs.validation.constants import SEVERITY_ERROR

logger = logging.getLogger("kdk.core")

CHECK_SEQUENCE = [
    ("Variables", "check_variables"),
    ("Maps", "check_maps"),
    ("Includes", "check_includes"),
    ("Labels", "check_labels"),
    ("Fonts", "check_fonts"),
    ("IDs", "check_ids"),
    ("Images", "check_images"),
    ("XML Validation", "check_values"),
    ("File Integrity", "check_file_integrity"),
    ("Kodi Repo", "check_repo"),
]


def filter_include_warnings(all_issues: dict) -> dict:
    """Drop the warnings that come from include content, keeping its errors."""
    filtered = {}
    for category, issues in all_issues.items():
        filtered[category] = [
            i for i in issues
            if not (i.get("include_name") and i.get("severity") != "error")
        ]
    return filtered


def validate_skin(
    skin_path: str,
    *,
    config_overrides: dict | None = None,
    isolated: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Validate a skin with every check; returns issues, release, notices, timing, or an error."""
    skin_path = os.path.abspath(skin_path)
    config = load_config(skin_path, config_overrides, isolated)
    settings = Settings(config)
    total_steps = len(CHECK_SEQUENCE)

    def progress(step: int, msg: str):
        if progress_callback:
            progress_callback(step, total_steps, msg)

    addon_xml = os.path.join(skin_path, "addon.xml")
    if not os.path.isfile(addon_xml):
        return {
            "issues": {},
            "skin_name": "",
            "skin_path": skin_path,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": 0.0,
            "error": f"No addon.xml found at {skin_path}",
        }

    progress(0, "Initializing...")

    provider = InfoProvider()
    provider.load_settings(settings)
    provider.init_addon(skin_path)

    if not provider.addon:
        return {
            "issues": {},
            "skin_name": "",
            "skin_path": skin_path,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": 0.0,
            "error": f"Failed to load addon at {skin_path}",
        }

    # a reused Skin would carry stale resolved trees
    cache = getattr(provider.addon, "_resolved_windows_cache", None)
    if isinstance(cache, dict):
        cache.clear()

    fatal = getattr(provider, "_fatal_xml_error", None)
    if fatal:
        return {
            "issues": {},
            "skin_name": "",
            "skin_path": skin_path,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": 0.0,
            "error": f"XML parse error in {os.path.basename(fatal)} - fix this file before validating",
        }

    skin_name = getattr(provider.addon, "name", "") or os.path.basename(skin_path)

    start_time = time.time()
    all_issues = {}

    for step, (name, method_name) in enumerate(CHECK_SEQUENCE, 1):
        progress(step, f"Checking {name.lower()}...")

        def step_progress(message, _step=step, _name=name):
            progress(_step, f"{_name}: {message}")

        method = getattr(provider, method_name, None)
        if method:
            try:
                all_issues[name] = method(progress_callback=step_progress) or []
            except Exception as e:
                logger.error("Check %s failed: %s", name, e, exc_info=True)
                provider.addon.add_notice(f"The {name} check failed, so its results are missing: {e}")
                # without a severity the row is filtered out and the run exits 0
                all_issues[name] = [{
                    "message": f"Check failed: {e}",
                    "file": "", "line": 0, "severity": SEVERITY_ERROR,
                    "rule": "kdk.check-failed", "subject": name,
                }]
        else:
            logger.warning("Check method %s not found", method_name)

    duration = time.time() - start_time
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "issues": all_issues,
        "skin_name": skin_name,
        "skin_path": skin_path,
        "timestamp": timestamp,
        "duration": duration,
        "kodi_release": provider.addon.api_version,
        "info_source": provider.info_source,
        "notices": list(provider.addon.notices),
        "error": None,
    }


def get_downloads_folder() -> str:
    """Return the OS default Downloads folder, or home as fallback."""
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if os.path.isdir(downloads):
        return downloads
    return home


def save_report(result: dict, output_path: str | None = None) -> str:
    """Save a validate result as a text report, by default a timestamped file in Downloads."""
    if output_path is None:
        safe_name = "".join(
            c if c.isalnum() or c in ("-", "_") else "_"
            for c in result["skin_name"]
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(get_downloads_folder(), f"{safe_name}_{ts}_report.txt")

    generate_text_report(
        all_issues=result["issues"],
        skin_name=result["skin_name"],
        skin_path=result["skin_path"],
        output_path=output_path,
    )

    return output_path
