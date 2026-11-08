"""FastAPI 应用：REST API + 静态前端。"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .constants import MAX_AUDIO_BYTES, SUPPORTED_AUDIO_EXTENSIONS
from .paths import project_root
from .player import PlayerError
from .service import BellService
from .storage import Storage


class ScheduleBody(BaseModel):
    time: str
    name: str
    audio_id: str
    weekdays: list[int] = Field(default_factory=list)
    enabled: bool = True


class EnabledBody(BaseModel):
    enabled: bool


class SettingsBody(BaseModel):
    volume: int | None = None
    paused: bool | None = None


class ConfigBody(BaseModel):
    content: str


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc).strip("'"))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PlayerError):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, OSError):
        return HTTPException(status_code=500, detail=f"文件操作失败：{exc}")
    return HTTPException(status_code=500, detail=str(exc))


async def _save_uploads(
    files: list[UploadFile],
    folder: Path,
) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    errors: list[str] = []
    used: set[str] = set()
    for index, upload in enumerate(files):
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
            errors.append(f"{upload.filename or '未命名文件'}：不支持的格式")
            continue
        raw_name = (upload.filename or f"audio-{index}{suffix}").replace("\\", "/")
        original = Path(raw_name).name or f"audio-{index}{suffix}"
        target = folder / original
        counter = 2
        while target.name.casefold() in used:
            target = folder / f"{Path(original).stem} ({counter}){suffix}"
            counter += 1
        used.add(target.name.casefold())
        size = 0
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise ValueError("文件超过 300 MB")
                    handle.write(chunk)
            if size <= 0:
                raise ValueError("文件为空")
            paths.append(target)
        except (OSError, ValueError) as exc:
            target.unlink(missing_ok=True)
            errors.append(f"{original}：{exc}")
        finally:
            await upload.close()
    return paths, errors


def create_app(data_dir: Path | None = None) -> FastAPI:
    storage = Storage(data_dir)
    storage.ensure_dirs()
    service = BellService(storage)
    frontend = project_root() / "frontend"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.start()
        try:
            yield
        finally:
            service.shutdown()

    app = FastAPI(
        title="自动铃声系统 API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.storage = storage
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "service": "autobell"}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return service.state()

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        try:
            return {
                "content": service.get_config_text(),
                "path": str(storage.config_path),
            }
        except OSError as exc:
            raise _service_error(exc) from exc

    @app.put("/api/config")
    def put_config(body: ConfigBody) -> dict[str, Any]:
        try:
            service.apply_config_text(body.content)
            return {"ok": True, "message": "配置已保存并重新加载"}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.post("/api/config/reload")
    def reload_config() -> dict[str, Any]:
        try:
            service.reload_config()
            return {"ok": True, "message": "配置已重新加载"}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.get("/api/export")
    def export_data() -> FileResponse:
        try:
            target = service.export_bundle()
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc
        return FileResponse(
            path=target,
            media_type="application/zip",
            filename=f"自动铃声系统-数据备份-{datetime.now():%Y%m%d-%H%M}.zip",
        )

    @app.post("/api/import")
    async def import_data(file: UploadFile = File(...)) -> dict[str, Any]:
        if Path(file.filename or "").suffix.lower() != ".zip":
            raise HTTPException(status_code=400, detail="请选择 .zip 数据包")
        temp_root = Path(tempfile.mkdtemp(prefix="upload-", dir=str(storage.base_dir)))
        target = temp_root / "data.zip"
        try:
            with target.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    handle.write(chunk)
            if target.stat().st_size <= 0:
                raise HTTPException(status_code=400, detail="数据包为空")
            result = service.import_bundle(target)
            return {
                "ok": True,
                "message": "导入完成",
                "backup": str(result.backup_path),
            }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc
        finally:
            await file.close()
            shutil.rmtree(temp_root, ignore_errors=True)

    @app.post("/api/audios")
    async def upload_audios(
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        temp_root = Path(tempfile.mkdtemp(prefix="upload-", dir=str(storage.base_dir)))
        try:
            paths, errors = await _save_uploads(files, temp_root)
            if not paths:
                raise HTTPException(
                    status_code=400,
                    detail="；".join(errors) if errors else "没有可导入的音频文件",
                )
            added, import_errors = service.add_audio_files(paths)
            errors.extend(import_errors)
            return {
                "ok": True,
                "added": [a.to_dict() for a in added],
                "errors": errors,
            }
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @app.delete("/api/audios/{audio_id}")
    def delete_audio(audio_id: str) -> dict[str, Any]:
        try:
            service.delete_audio(audio_id)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.post("/api/audios/{audio_id}/preview")
    def preview_audio(audio_id: str) -> dict[str, Any]:
        try:
            service.preview_audio(audio_id)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.post("/api/schedules")
    def create_schedule(body: ScheduleBody) -> dict[str, Any]:
        try:
            schedule = service.add_schedule(body.model_dump())
            return {"ok": True, "schedule": schedule.to_dict()}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.put("/api/schedules/{schedule_id}")
    def update_schedule(schedule_id: str, body: ScheduleBody) -> dict[str, Any]:
        try:
            schedule = service.update_schedule(schedule_id, body.model_dump())
            return {"ok": True, "schedule": schedule.to_dict()}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.patch("/api/schedules/{schedule_id}")
    def patch_schedule(schedule_id: str, body: EnabledBody) -> dict[str, Any]:
        try:
            schedule = service.set_schedule_enabled(schedule_id, body.enabled)
            return {"ok": True, "schedule": schedule.to_dict()}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.delete("/api/schedules/{schedule_id}")
    def delete_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            service.delete_schedule(schedule_id)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.delete("/api/schedules")
    def clear_schedules() -> dict[str, Any]:
        try:
            service.clear_schedules()
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.post("/api/schedules/template")
    def apply_template() -> dict[str, Any]:
        try:
            schedules = service.apply_template()
            return {"ok": True, "count": len(schedules)}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.post("/api/schedules/{schedule_id}/preview")
    def preview_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            service.preview_schedule(schedule_id)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.patch("/api/settings")
    def patch_settings(body: SettingsBody) -> dict[str, Any]:
        try:
            settings = service.set_settings(body.volume, body.paused)
            return {"ok": True, "settings": settings.to_dict()}
        except Exception as exc:  # noqa: BLE001
            raise _service_error(exc) from exc

    @app.post("/api/stop")
    def stop_playback() -> dict[str, Any]:
        service.stop_playback()
        return {"ok": True}

    @app.get("/api/logs")
    def logs() -> dict[str, Any]:
        return {"logs": service.state()["logs"]}

    # 静态前端与音频文件
    app.mount("/media", StaticFiles(directory=str(storage.audio_dir)), name="media")
    app.mount("/static", StaticFiles(directory=str(frontend)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html")

    return app
