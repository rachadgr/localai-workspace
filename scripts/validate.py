#!/usr/bin/env python3
"""Full validation: dependency check, tests, artifact smoke, API smoke."""
from __future__ import annotations
import importlib, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

REQUIRED = ["fastapi","uvicorn","pydantic","pydantic_settings","sqlalchemy","psycopg","jwt","bcrypt",
            "requests","docx","openpyxl","reportlab","pptx","pandas","trafilatura","markdown"]

def check_deps() -> bool:
    missing = []
    for mod in REQUIRED:
        try: importlib.import_module(mod)
        except Exception: missing.append(mod)
    print(("deps: OK (%d)" % len(REQUIRED)) if not missing else f"deps: MISSING {missing}")
    return not missing

def run(cmd: list[str]) -> bool:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT)) == 0

def main() -> int:
    ok = check_deps()
    ok &= run([sys.executable, "-m", "pytest", "tests", "-q"])
    ok &= run([sys.executable, "-m", "scripts.smoke"])
    print("\nVALIDATION:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
