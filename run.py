"""自动铃声系统 Web 版启动入口。"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import webbrowser
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
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Web 版")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    storage = Storage()
    storage.ensure_dirs()
    configure_logging(storage.log_dir)
    logger = logging.getLogger("autobell")
    logger.info("========== %s v%s Web 版启动 ==========", APP_NAME, APP_VERSION)
    logger.info("数据目录：%s", storage.base_dir)

    app = create_app(storage.base_dir)
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    logger.info("打开浏览器访问：%s", url)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
