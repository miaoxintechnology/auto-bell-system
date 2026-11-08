"""全局常量。"""

from __future__ import annotations

APP_NAME = "自动铃声系统"
APP_NAME_EN = "Auto Bell"
APP_VERSION = "1.0.0"
DATA_DIR_NAME = "AutoBellSystem"
AUTOSTART_KEY = "AutoBellSystem"
LOG_FILENAME = "autobell.log"
LOCAL_SERVER_NAME = "AutoBellSystem-SingleInstance-v1"

WEEKDAY_NAMES: dict[int, str] = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}
WEEKDAY_SHORT: dict[int, str] = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "日",
}

SUPPORTED_AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".m4a",
    ".aac",
    ".wma",
)

AUDIO_FILTER = (
    "音频文件 (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.wma);;所有文件 (*.*)"
)
MAX_AUDIO_BYTES = 300 * 1024 * 1024  # 300 MiB
