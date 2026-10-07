"""Environment bootstrap for the local Whisper stack.

Import this module *before* importing ctranslate2 / faster_whisper.

The CUDA runtime ships inside the `nvidia-*` wheels rather than in the system,
and CTranslate2 loads those libraries by bare file name. Registering the
directories is not enough on its own, so every library is also preloaded by
full path: once loaded, Windows resolves the bare-name lookups to the already
loaded module.
"""

import ctypes
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Where the faster-whisper stack lives. Override with CODEX_SUBS_LIBS when the
# install has moved; the second entry is where this user's copy was installed.
LIBS = os.environ.get("CODEX_SUBS_LIBS") or \
    r"C:\Users\31K\Documents\Codex\2026-09-12\wo-yuu\work\pylibs"
if not os.path.isdir(LIBS):
    raise SystemExit(
        f"找不到 Python 依赖目录: {LIBS}\n"
        "请把它移到目标位置，然后设置环境变量 CODEX_SUBS_LIBS 指向新目录。"
    )


def setup(libs=LIBS):
    if libs not in sys.path:
        sys.path.insert(0, libs)
    bins = glob.glob(os.path.join(libs, "nvidia", "*", "bin"))
    for d in bins:
        try:
            os.add_dll_directory(d)
        except (AttributeError, OSError):
            pass
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    loaded, failed = [], []
    for d in bins:
        for path in sorted(glob.glob(os.path.join(d, "*.dll"))):
            name = os.path.basename(path)
            try:
                ctypes.WinDLL(path)
                loaded.append(name)
            except OSError as e:
                failed.append(f"{name}: {e}")
    return loaded, failed


if __name__ == "__main__":
    ok, bad = setup()
    print(f"preloaded {len(ok)} CUDA libraries")
    for b in bad:
        print("  failed:", b)
