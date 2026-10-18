"""Data loading and initialization mixin for `InfoProvider`."""

from __future__ import annotations

import os
import json
import copy
import logging
from typing import Any

from lxml.etree import XMLSyntaxError

from ..utils.infobool import info_name_sets
from ..utils.xml import get_root_from_file
from ..addon.addon import Addon

logger = logging.getLogger(__name__)


class LoaderMixin:
    """Handles loading Kodi data, addon initialization, and settings."""

    addon: Any
    template_root: Any
    WINDOW_FILENAMES: list
    WINDOW_NAMES: list
    WINDOW_IDS: list
    MODELESS_IDS: set
    DIALOG_IDS: set
    OBSOLETE_WINDOW_FILES: dict
    INFO_NAMES: dict
    builtins: list
    conditions: list
    template_attribs: dict
    template_values: dict
    settings: dict
    kodi_path: str | None
    _fatal_xml_error: str | None

    def load_data(self, kodi_version="omega"):
        """Load a Kodi version's controls, builtins, conditions, window maps and info names."""
        data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", kodi_version))

        self.template_root = get_root_from_file(
            os.path.join(data_dir, "controls.xml")
        )
        root = get_root_from_file(
            os.path.join(data_dir, "data.xml")
        )
        with open(os.path.join(data_dir, "windows.json"), "r") as f:
            WINDOW_MAP = json.load(f)
        with open(os.path.join(data_dir, "obsolete_windows.json"), encoding="utf-8") as f:
            self.OBSOLETE_WINDOW_FILES = json.load(f)
        with open(os.path.join(data_dir, "infonames.json"), encoding="utf-8") as f:
            self.INFO_NAMES = info_name_sets(json.load(f))

        if root is None:
            raise ValueError(f"Failed to load data.xml for Kodi version {kodi_version}")
        if self.template_root is None:
            raise ValueError(f"Failed to load controls.xml for Kodi version {kodi_version}")

        self.WINDOW_FILENAMES = [item[2] for item in WINDOW_MAP]
        self.WINDOW_NAMES = [item[0] for item in WINDOW_MAP]
        self.WINDOW_IDS = [str(item[1]) for item in WINDOW_MAP]
        self.MODELESS_IDS = {str(item[1]) for item in WINDOW_MAP if item[3] == "modeless"}
        self.DIALOG_IDS = {str(item[1]) for item in WINDOW_MAP if item[3] != "window"}

        builtins_elem = root.find("builtins")
        self.builtins = [
            [i.find("code").text, i.find("help").text] for i in builtins_elem
        ] if builtins_elem is not None else []

        conditions_elem = root.find("conditions")
        self.conditions = [
            [i.find("code").text, i.find("help").text] for i in conditions_elem
        ] if conditions_elem is not None else []

        for include in self.template_root.xpath("//include[@name]"):
            for node in self.template_root.xpath("//include[not(@*)]"):
                if node.text == include.attrib.get("name"):
                    for child in include.getchildren():
                        node.getparent().append(copy.deepcopy(child))
                    node.getparent().remove(node)
            self.template_root.remove(include)

        self.template_attribs = {}
        self.template_values = {}
        for template in self.template_root:
            ctype = template.attrib.get("type")
            if not ctype:
                continue

            attribs = {}
            for k, v in template.attrib.items():
                if k == "type":
                    continue
                attribs[k] = v

            for i in template.iterchildren():
                attribs[i.tag] = i.attrib

            self.template_attribs[ctype] = attribs
            self.template_values[template.attrib.get("type")] = {
                i.tag: i.text for i in template.iterchildren()
            }

    def init_addon(self, path):
        """Initialize the addon, noting Kodi data that fails to load and recording the bad XML."""
        self.addon = None
        self._fatal_xml_error = None
        addon_xml = os.path.join(path, "addon.xml")
        if not os.path.exists(addon_xml):
            return

        logger.info("Kodi project detected: %s", addon_xml)
        self.addon = Addon.by_project(path, self.settings)

        try:
            kodi_ver = getattr(self.addon, "api_version", "omega")
            self.load_data(kodi_ver)
        except Exception as e:
            logger.warning("Failed to load control schema: %s", e)
            if self.addon:
                self.addon.add_notice(f"Kodi's {kodi_ver} data could not be loaded, so checks that need it are incomplete: {e}")

        if not self.addon:
            return

        for xml_path in self.addon.get_xml_files():
            try:
                root = get_root_from_file(xml_path)
                if root is None:
                    raise XMLSyntaxError("Unparseable file", xml_path, 0, 0)
            except XMLSyntaxError:
                logger.error("Unparseable file: %s", os.path.basename(xml_path), exc_info=True)
                self._fatal_xml_error = xml_path
                return

    def load_settings(self, settings):
        """Load the settings and the Kodi path they name."""
        self.settings = settings
        self.kodi_path = settings.get("kodi_path")
        logger.info("kodi path: %s", self.kodi_path)

