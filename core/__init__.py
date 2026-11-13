"""Pacote core do DevMaster / Concio Studio V2."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Garantir que executáveis instalados via pip (como composio e opencode) estejam no PATH do processo
_user_scripts = Path.home() / "AppData" / "Roaming" / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts"
_sys_scripts = Path(sys.executable).parent / "Scripts"
for _p in (_user_scripts, _sys_scripts):
    if _p.exists() and str(_p) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{_p};{os.environ.get('PATH', '')}"

