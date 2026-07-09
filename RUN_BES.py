import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BES" / "venv"
PYTHON = VENV / "Scripts" / "python.exe"
PYTHONW = VENV / "Scripts" / "pythonw.exe"
REQ = ROOT / "requirements.txt"
MAIN = ROOT / "main.py"


def run(cmd):
    return subprocess.run(cmd, cwd=str(ROOT))


def ensure_venv():
    if not PYTHON.exists():
        VENV.parent.mkdir(parents=True, exist_ok=True)
        result = run([sys.executable, "-m", "venv", str(VENV)])
        if result.returncode:
            return result.returncode
    result = run([str(PYTHON), "--version"])
    if result.returncode:
        print(f"Windows blocked the virtual environment Python: {PYTHON}")
        print(f"Delete this folder and try again: {VENV.parent}")
        return result.returncode
    if REQ.exists():
        run([str(PYTHON), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
        result = run([str(PYTHON), "-m", "pip", "install", "-r", str(REQ), "--quiet", "--upgrade"])
        if result.returncode:
            return result.returncode
    return 0


def main():
    os.chdir(ROOT)
    code = ensure_venv()
    if code:
        return code
    exe = PYTHONW if PYTHONW.exists() else PYTHON
    return subprocess.call([str(exe), str(MAIN)], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
