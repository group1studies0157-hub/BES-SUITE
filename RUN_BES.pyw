import ctypes
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
launcher = root / "RUN_BES.py"
try:
    subprocess.Popen([sys.executable, str(launcher)], cwd=str(root))
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(None, str(exc), "Bridge Engineering Suite", 0x10)
