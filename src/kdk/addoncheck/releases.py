"""Kodi repo branches and the core add-on versions each one accepts."""

from __future__ import annotations

from typing import NamedTuple

# oldest first; every branch the Kodi mirrors still serve
BRANCHES = ("gotham", "helix", "isengard", "jarvis", "krypton", "leia", "matrix", "nexus", "omega", "piers")

# branches a submission can target and this package checks
TARGETS = BRANCHES[BRANCHES.index("matrix"):]

PYTHON_FLOOR = (3, 8)

# newest Python every build of the branch has; code needing more fails on some of them
PYTHON_FLOORS = {"matrix": (3, 8), "nexus": (3, 8), "omega": (3, 8), "piers": (3, 9)}

# oldest Python packaged builds of the branch run; between floor and this only source builds break
PACKAGED_PYTHON = {"piers": (3, 13)}

# Python of the LTS distros a Kodi 22 source build takes its Python from
LTS_PYTHON = (("RHEL 9", (3, 9)), ("Ubuntu 22.04", (3, 10)), ("Debian 12", (3, 11)), ("Ubuntu 24.04", (3, 12)))


def python_level(branch: str, needed: tuple[int, int]) -> str | None:
    """How bad needing the Python version is on the branch: None, "hint" or "fail"."""
    if needed <= PYTHON_FLOORS[branch]:
        return None
    packaged = PACKAGED_PYTHON.get(branch)
    return "hint" if packaged and needed <= packaged else "fail"


def python_reason(branch: str, needed: tuple[int, int]) -> str:
    """Why code needing the Python version breaks on a branch with packaged builds, as a clause."""
    packaged = PACKAGED_PYTHON[branch]
    if needed <= packaged:
        older = ", ".join(f"{name} has {v[0]}.{v[1]}" for name, v in LTS_PYTHON if v < needed)
        return f"it breaks only source builds of Kodi 22 on older LTS distros ({older})"
    return f"packaged builds of Kodi 22 start at Python {packaged[0]}.{packaged[1]}"


class Abi(NamedTuple):
    """One core add-on on one branch: oldest import accepted, first shipped, advised."""

    floor: str
    ceiling: str
    advised: str


# the ceiling is the version in the branch's first release, which users still run
CORE = {
    "xbmc.python": {
        "matrix": Abi("3.0.0", "3.0.0", "3.0.0"),
        "nexus": Abi("3.0.0", "3.0.1", "3.0.1"),
        "omega": Abi("3.0.0", "3.0.1", "3.0.1"),
        "piers": Abi("3.0.0", "3.1.0", "3.0.1"),
    },
    "xbmc.gui": {
        "matrix": Abi("5.15.0", "5.15.0", "5.15.0"),
        "nexus": Abi("5.15.0", "5.16.0", "5.16.0"),
        "omega": Abi("5.17.0", "5.17.0", "5.17.0"),
        "piers": Abi("5.17.0", "5.18.0", "5.17.0"),
    },
    "xbmc.addon": {
        "matrix": Abi("12.0", "19.0.0", "19.1.0"),
        "nexus": Abi("12.0", "20.0.0", "20.0.0"),
        "omega": Abi("12.0", "21.0.0", "21.0.0"),
        "piers": Abi("12.0", "21.90.901", "21.90.700"),
    },
    "xbmc.json": {
        "matrix": Abi("6.0.0", "12.2.1", "12.4.0"),
        "nexus": Abi("6.0.0", "13.0.0", "13.0.0"),
        "omega": Abi("6.0.0", "13.5.0", "13.5.0"),
        "piers": Abi("6.0.0", "13.1000.0", "13.6.0"),
    },
    "xbmc.metadata": {branch: Abi("1.0", "2.1.0", "2.1.0") for branch in TARGETS},
}


def display(branch: str) -> str:
    """The branch as messages name it, such as Piers."""
    return branch.capitalize()


def possessive(branch: str) -> str:
    """The branch's possessive as messages write it, such as Piers' or Omega's."""
    name = display(branch)
    return name + ("'" if name.endswith("s") else "'s")


def lower(branch: str) -> tuple[str, ...]:
    """Branches older than the one given, oldest first."""
    return BRANCHES[:BRANCHES.index(branch)]


def higher(branch: str) -> tuple[str, ...]:
    """Branches newer than the one given, oldest first."""
    return BRANCHES[BRANCHES.index(branch) + 1:]
