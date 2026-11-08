"""应用路径解析。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .constants import DATA_DIR_NAME


def project_root() -> Path:
    """源码根目录；PyInstaller 打包后指向临时/内部资源目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    return project_root() / "assets" / name


def default_data_dir() -> Path:
    """配置、音频和日志的默认存放目录，可用环境变量覆盖。"""
    override = os.environ.get("AUTOBELL_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / DATA_DIR_NAME
    return Path.home() / "AppData" / "Roaming" / DATA_DIR_NAME
