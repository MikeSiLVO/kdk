"""Detect dynamic expressions (`$VAR`/`$INFO`/`$LOCALIZE`/`$PARAM`) and resolve `$PARAM` substitutions."""

from __future__ import annotations

import logging
import re
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger("kdk.utils.expressions")
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
logger.propagate = True

_PARAM_PATTERN = re.compile(r"\$PARAM\[\s*(?P<name>[A-Za-z0-9_\-]+)\s*\]", re.IGNORECASE)
_DEFAULT_DYNAMIC_PREFIXES = tuple(
    p.casefold()
    for p in (
        "$param[",
        "$var[",
        "$info[",
        "$addon[",
        "$escvar[",
        "$escinfo[",
    )
)


def is_number(text: str) -> bool:
    """Check if text is a valid finite number."""
    try:
        value = float(text)
        return value not in (float('inf'), float('-inf')) and value == value
    except ValueError:
        return False


def extract_number_value(text: str) -> str | None:
    """Return the inner number from `$NUMBER[N]` (or `None` if `text` isn't a valid `$NUMBER[...]`)."""
    if not isinstance(text, str):
        return None

    match = re.match(r'^\$NUMBER\[([^\]]+)\]$', text.strip(), re.IGNORECASE)
    if not match:
        return None

    value = match.group(1).strip()

    if is_number(value):
        return value

    return None


def extract_variable_name(text: str) -> str | None:
    """Return the variable name from `$VAR[Name,...]` / `$ESCVAR[Name,...]` (`None` if not a variable expression)."""
    if not isinstance(text, str):
        return None

    match = re.match(r'^\$(ESC)?VAR\[([^\]]+)\]', text.strip(), re.IGNORECASE)
    if not match:
        return None

    var_name = match.group(2).strip()

    if ',' in var_name:
        var_name = var_name.split(',')[0].strip()

    return var_name if var_name else None


def resolve_params_in_text(text: str, params: Optional[dict[str, str]] = None) -> tuple[str, str]:
    """Substitute `$PARAM[k]` with `params[k]` (XML-escaped); missing keys stay literal. Returns `(text, status)` where `status` is `NO_PARAMS`/`ALL_RESOLVED`/`PARTIAL_RESOLVED`/`SINGLE_UNDEFINED`."""
    if not text or not isinstance(text, str):
        return text, "NO_PARAMS"
    if not params:
        if _PARAM_PATTERN.search(text):
            matches = _PARAM_PATTERN.findall(text)
            if len(matches) == 1:
                return text, "SINGLE_UNDEFINED"
            return text, "PARTIAL_RESOLVED"
        return text, "NO_PARAMS"

    total_params = 0
    undefined_params = 0

    def _sub(m):
        nonlocal total_params, undefined_params
        total_params += 1
        key = m.group("name")
        val = params.get(key)
        if val is not None:
            return xml_escape(val)
        undefined_params += 1
        return m.group(0)

    result = _PARAM_PATTERN.sub(_sub, text)

    if total_params == 0:
        status = "NO_PARAMS"
    elif undefined_params == 0:
        status = "ALL_RESOLVED"
    elif total_params == 1 and undefined_params == 1:
        status = "SINGLE_UNDEFINED"
    else:
        status = "PARTIAL_RESOLVED"

    return result, status


def is_dynamic_expression(text: str, *, prefixes: Optional[tuple[str, ...]] = None) -> bool:
    """`True` if `text` (after trimming) starts with one of `prefixes` (default: `$PARAM[`/`$VAR[`/`$INFO[`/`$ADDON[`/`$ESCVAR[`/`$ESCINFO[`); case-insensitive."""
    if not isinstance(text, str):
        return False
    candidate = text.strip()
    if not candidate:
        return False
    lowered = candidate.casefold()
    if prefixes:
        checks = tuple(p.casefold() for p in prefixes)
    else:
        checks = _DEFAULT_DYNAMIC_PREFIXES
    return any(lowered.startswith(pref) for pref in checks)


def starts_with_param_reference(text: str) -> bool:
    """Check if text starts with a $PARAM[...] expression."""
    return is_dynamic_expression(text, prefixes=("$param[",))


def contains_dynamic_expression(text: str) -> bool:
    """`True` if a dynamic expression appears anywhere in `text` (vs `is_dynamic_expression` which only checks the start)."""
    if not isinstance(text, str):
        return False
    if not text:
        return False

    lowered = text.casefold()
    return any(pref in lowered for pref in _DEFAULT_DYNAMIC_PREFIXES)


_EXP_PATTERN = re.compile(r"\$EXP\[\s*([A-Za-z0-9_\-]+)\s*\]", re.IGNORECASE)


def flatten_expressions(text: str, expression_map: dict[str, str],
                        _resolved: Optional[list[str]] = None) -> tuple[str, set[str]]:
    """Expand `$EXP[name]` recursively; returns the text and any undefined names.

    Mirrors CGUIIncludes::FlattenExpression (GUIIncludes.cpp:213-242). Undefined
    names are left in place, not erased as Kodi does (GUIIncludes.cpp:663), so a
    caller can tell "no such expression" from a genuinely empty body.
    """
    if not text:
        return text, set()

    resolved = _resolved or []
    unknown: set[str] = set()

    def replacer(match):
        name = match.group(1)
        if name in resolved:
            logger.error('Skin has a circular expression "%s": %s', resolved[-1], text)
            return ""
        if name not in expression_map:
            unknown.add(name)
            return match.group(0)
        body, nested_unknown = flatten_expressions(
            expression_map[name], expression_map, resolved + [name]
        )
        unknown.update(nested_unknown)
        return body

    return _EXP_PATTERN.sub(replacer, text), unknown


def get_param_names_in_context(include_node, xpath_pattern: str) -> set[str]:
    """Return param names appearing in `$PARAM[...]` references within nodes matched by `xpath_pattern` under `include_node`."""
    if include_node is None:
        return set()

    param_names = set()

    try:
        matches = include_node.xpath(xpath_pattern)

        for match in matches:
            if not match or not isinstance(match, str):
                continue

            for param_match in _PARAM_PATTERN.finditer(match):
                param_name = param_match.group("name")
                if param_name:
                    param_names.add(param_name)

    except Exception:
        logger.exception("Error extracting param names with pattern %s", xpath_pattern)

    return param_names
