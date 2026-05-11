"""Wrap Kodi's `TexturePacker` to build a `.xbt` from a media directory."""

import os
import subprocess
import logging

logger = logging.getLogger("kdk.skin.textures")
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
logger.propagate = True


def texturepacker(media_path, settings, xbt_filename="Textures.xbt"):
    """Run `TexturePacker` (path from `settings`) on `media_path`, writing `<media_path>/<xbt_filename>`."""
    tp_path = settings.get("texturepacker_path")
    if not tp_path:
        return None
    args = ['-dupecheck',
            '-input "%s"' % media_path,
            '-output "%s"' % os.path.join(media_path, xbt_filename)]
    import platform as _platform_mod
    _plat = "linux" if _platform_mod.system() == "Linux" else "other"
    if _plat == "linux":
        args = ['%s %s' % (tp_path, " ".join(args))]
    else:
        args.insert(0, tp_path)
    with subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
        shell=True,
    ) as p:
        if p.stdout:
            for line in p.stdout:
                logger.warning(line)
