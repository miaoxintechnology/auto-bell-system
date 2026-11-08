"""Electron 内置后端启动入口（供 PyInstaller 打包）。"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from backend.api import create_app
from backend.constants import APP_NAME, APP_VERSION
from backend.storage import Storage


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_dir / "autobell.log",
        maxBytes=768 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} 后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["AUTOBELL_DATA_DIR"] = args.data_dir

    storage = Storage()
    storage.ensure_dirs()
    configure_logging(storage.log_dir)
    logger = logging.getLogger("autobell")
    logger.info("========== %s v%s 后端启动 ==========", APP_NAME, APP_VERSION)
    logger.info("数据目录：%s", storage.base_dir)
    app = create_app(storage.base_dir)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
