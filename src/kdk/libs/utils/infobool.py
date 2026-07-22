"""Boolean-condition syntax checking, mirroring Kodi's InfoExpression parser.

Kodi evaluates a condition it cannot parse as a constant `false`
(InfoExpression.cpp:34-42), so the skin never sees the error. `check_condition`
catches it statically and says why.
"""

from __future__ import annotations

import re

STATE_INVALID = "invalid"
STATE_NEEDS_CONTEXT = "needs_context"

_OPERATORS = "[]!+|"

# Substituted just before parsing by CGUIInfoLabel::ReplaceLocalize
# (GUIInfoManager.cpp:11441), so their brackets never reach the parser.
# Case-sensitive: Kodi matches the literal "$LOCALIZE[" (GUIInfoLabel.cpp:196),
# so `$Localize[1]` keeps its bracket and fails the parse.
_PRESUBSTITUTED = re.compile(r"\$(?:LOCALIZE|NUMBER)\[")

# Label-side macros. Nothing expands them in a boolean condition, so their `[`
# lands after operand characters and Kodi rejects the whole expression.
_LABEL_MACRO = re.compile(r"\$(VAR|ESCVAR|INFO|ESCINFO|ADDON)\[", re.IGNORECASE)

_PARAM = re.compile(r"\$PARAM\[", re.IGNORECASE)
_EXP = re.compile(r"\$EXP\[\s*([A-Za-z0-9_\-]+)\s*\]", re.IGNORECASE)
_CASED_KEYWORD = re.compile(r"\$(?:localize|number)\[", re.IGNORECASE)


def _drop_presubstituted(text: str) -> tuple[str, bool]:
    """Swap `$LOCALIZE[..]` / `$NUMBER[..]` for a placeholder operand.

    Returns the text and whether a reference was left unclosed. Kodi stops
    replacing at one and leaves it in (GUIInfoLabel.cpp:214-218), so its `[`
    still reaches the parser.
    """
    out = []
    pos = 0
    unclosed = False
    while True:
        match = _PRESUBSTITUTED.search(text, pos)
        if not match:
            break
        depth = 1
        i = match.end()
        while i < len(text) and depth:
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
            i += 1
        if depth:
            unclosed = True
            break
        out.append(text[pos:match.start()])
        out.append("_")
        pos = i
    out.append(text[pos:])
    return "".join(out), unclosed


def _has_miscased_keyword(text: str) -> bool:
    """True when `$LOCALIZE[` / `$NUMBER[` appears in a case Kodi won't match."""
    return any(m.group(0) != m.group(0).upper() for m in _CASED_KEYWORD.finditer(text))


def check_syntax(condition: str) -> str | None:
    """Why Kodi cannot parse `condition`, or None when it parses.

    Ports the syntax checks in InfoExpression::Parse (InfoExpression.cpp:206-303).
    Operand names are not checked: Kodi accepts any name and evaluates an unknown
    one as false (GUIInfoManager.cpp:11444), so a bad name is not a parse error.
    """
    text, unclosed = _drop_presubstituted(condition)
    if unclosed:
        return "missing ']' in $LOCALIZE / $NUMBER"
    text = text.strip()
    if not text:
        return "empty condition"

    after_binary = True
    brackets = 0
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        i += 1
        if char not in _OPERATORS:
            after_binary = False
            continue

        if (not after_binary and char in "![") or (after_binary and char in "]+|"):
            reason = f"misplaced '{char}'"
            if char == "[" and _has_miscased_keyword(condition):
                reason += " ($LOCALIZE / $NUMBER must be uppercase)"
            return reason
        if char == "[":
            brackets += 1
        elif char == "]":
            if brackets == 0:
                return "unmatched ']'"
            brackets -= 1
        if char in "+|":
            after_binary = True
        while i < n and text[i].isspace():
            i += 1

    if brackets:
        return "unmatched '['"
    if after_binary:
        return "missing operand"
    return None


def check_condition(condition: str) -> tuple[str, str] | None:
    """The `(state, reason)` blocking `condition`, or None when it can be sent to Kodi.

    Expects `$EXP` already flattened: a leftover reference means the skin never
    defined it, which Kodi erases to nothing at load (GUIIncludes.cpp:663).
    """
    if _PARAM.search(condition):
        return STATE_NEEDS_CONTEXT, "unresolved $PARAM"

    unknown = _EXP.search(condition)
    if unknown:
        return STATE_INVALID, f"unknown expression {unknown.group(1)}"

    macro = _LABEL_MACRO.search(condition)
    if macro:
        return STATE_INVALID, f"${macro.group(1).upper()}[] is not valid inside a boolean condition"

    reason = check_syntax(condition)
    if reason:
        return STATE_INVALID, reason
    return None
