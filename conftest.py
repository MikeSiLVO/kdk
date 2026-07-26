"""Test bootstrap for kdk.

The suite is shared verbatim with KodiDevKit, which imports the engine as
`libs.*`. Aliasing `kdk.libs` onto that name keeps the test files identical
in both repos.
"""

import importlib
import pkgutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "tests"))

# The shared tests run inside Sublime's plugin host, where this is real.
import mock_sublime  # noqa: E402

sys.modules.setdefault("sublime", mock_sublime)
sys.modules.setdefault("sublime_api", mock_sublime)

import kdk.libs as _libs  # noqa: E402

sys.modules["libs"] = _libs
for _mod in pkgutil.walk_packages(_libs.__path__, prefix="kdk.libs."):
    try:
        sys.modules["libs" + _mod.name[len("kdk.libs"):]] = importlib.import_module(_mod.name)
    except ImportError:
        pass
