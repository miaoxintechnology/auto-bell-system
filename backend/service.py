"""铃声业务服务：状态、调度、播放、配置与数据包。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .constants import APP_NAME, APP_VERSION
from .models import (
    AppData,
    AudioAsset,
    Schedule,
    Settings,
    due_for,
    next_bell,
    parse_time,
    relative_day,
    seeded_schedules,
)
from .player import AudioPlayer, PlayerError
from .storage import ImportResult, LoadResult, Storage

logger = logging.getLogger("autobell")


class BellScheduler(threading.Thread):
    def __init__(self, service: "BellService") -> None:
        super().__init__(name="bell-scheduler", daemon=True)
        self._service = service
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(0.2):
            try:
                self._service.tick()
            except Exception:  # noqa: BLE001
                logger.exception("调度线程异常")
                self._service.add_log("调度线程出现异常，请检查日志", "error")

    def stop(self) -> None:
        self._stop.set()


class BellService:
    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage or Storage()
        self.load_result: LoadResult = self.storage.bootstrap()
        self.data: AppData = self.load_result.data
        self.lock = threading.RLock()
        self.player = AudioPlayer(self.data.settings.volume)
        self.revision = 0
        self.logs: deque[tuple[str, str, str]] = deque(maxlen=120)
        self._fired: set[str] = set()
        self._fired_day = ""
        self._playing_schedule_id = ""
        self._scheduler = BellScheduler(self)
        self._started = False
        if self.load_result.warning:
            self.add_log(self.load_result.warning, "warn")
        self.add_log("服务已启动，等待作息安排", "info")

    # ------------------------------------------------------------------
    def start(self) -> None:
        with self.lock:
            if self._started:
                return
            self._started = True
            self._scheduler.start()
            self.add_log("自动调度已启动", "info")

    def shutdown(self) -> None:
        with self.lock:
            self._scheduler.stop()
            self.player.shutdown()
            self._started = False

    def add_log(self, text: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append((stamp, text, level))
        self.revision += 1
        if level == "error":
            logger.error(text)
        elif level == "warn":
            logger.warning(text)
        else:
            logger.info(text)

    # ------------------------------------------------------------------
    def tick(self, now: datetime | None = None) -> list[Schedule]:
        moment = now or datetime.now()
        with self.lock:
            today = moment.date().isoformat()
            if self._fired_day != today:
                self._fired.clear()
                self._fired_day = today
            if self.data.settings.paused:
                return []
            triggered: list[Schedule] = []
            for schedule in self.data.sorted_schedules():
                occurrence = due_for(schedule, moment)
                if occurrence is None:
                    continue
                key = f"{occurrence.date().isoformat()}|{schedule.id}|{schedule.time}"
                if key in self._fired:
                    continue
                self._fired.add(key)
                triggered.append(schedule)
                self._play_schedule_locked(schedule, actual=True)
            return triggered

    def _play_schedule_locked(self, schedule: Schedule, actual: bool) -> bool:
        asset = self.data.find_audio(schedule.audio_id)
        if asset is None:
            self.add_log(f"{schedule.time} {schedule.name} 未播放：音频缺失", "error")
            return False
        path = self.storage.audio_path(asset)
        if not path.is_file():
            self.add_log(f"{schedule.time} {schedule.name} 未播放：音频文件缺失", "error")
            return False
        try:
            self.player.play(path, asset.name, asset.id)
        except PlayerError as exc:
            self.add_log(str(exc), "error")
            return False
        self._playing_schedule_id = schedule.id
        action = "响铃" if actual else "试听"
        self.add_log(f"{schedule.time} · {schedule.name} {action}：{asset.name}", "ok" if actual else "info")
        return True

    def _ensure_player_idle(self) -> None:
        if not self.player.is_playing():
            self._playing_schedule_id = ""

    # ------------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        with self.lock:
            playing = self.player.status()
            if playing is None and self._playing_schedule_id:
                self._playing_schedule_id = ""
                self.revision += 1
            now = datetime.now()
            schedules = self.data.sorted_schedules()
            result = next_bell(schedules, now)
            next_schedule, next_time = result if result else (None, None)
            next_id = next_schedule.id if next_schedule else ""
            today_items = [s for s in schedules if s.occurs_on(now.date())]
            active_today = [s for s in today_items if s.enabled]
            done_count = sum(1 for s in active_today if s.time_value <= now.time())
            schedule_payload = []
            for schedule in schedules:
                target = schedule.next_occurrence(now)
                schedule_payload.append(
                    {
                        **schedule.to_dict(),
                        "weekday_text": schedule.weekday_text,
                        "next_occurrence": target.isoformat(timespec="seconds")
                        if target
                        else None,
                        "next_text": (
                            f"{relative_day(target, now)} {target:%H:%M}"
                            if target
                            else "—"
                        ),
                        "status": self._status_for(
                            schedule, next_id, now, playing
                        ),
                    }
                )
            audio_payload = []
            for asset in self.data.audios:
                path = self.storage.audio_path(asset)
                usage = sum(1 for s in self.data.schedules if s.audio_id == asset.id)
                audio_payload.append(
                    {
                        **asset.to_dict(),
                        "url": f"/media/{quote(asset.filename)}",
                        "usage": usage,
                        "exists": path.is_file(),
                        "size": path.stat().st_size if path.is_file() else asset.size_bytes,
                    }
                )
            next_payload = None
            if next_schedule and next_time:
                next_payload = {
                    "schedule_id": next_schedule.id,
                    "name": next_schedule.name,
                    "time": next_schedule.time,
                    "occurrence": next_time.isoformat(timespec="seconds"),
                    "relative": relative_day(next_time, now),
                    "audio_id": next_schedule.audio_id,
                }
            return {
                "app_name": APP_NAME,
                "app_version": APP_VERSION,
                "revision": self.revision,
                "server_time": now.isoformat(timespec="seconds"),
                "date": now.date().isoformat(),
                "weekday": now.isoweekday(),
                "schedules": schedule_payload,
                "audios": audio_payload,
                "settings": self.data.settings.to_dict(),
                "next": next_payload,
                "today": {
                    "count": len(active_today),
                    "done": done_count,
                    "remaining": len(active_today) - done_count,
                },
                "playing": (
                    {
                        **playing,
                        "schedule_id": self._playing_schedule_id,
                    }
                    if playing
                    else None
                ),
                "logs": [
                    {"time": stamp, "text": text, "level": level}
                    for stamp, text, level in list(self.logs)[-10:][::-1]
                ],
                "config_path": str(self.storage.config_path),
                "data_dir": str(self.storage.base_dir),
                "audio_dir": str(self.storage.audio_dir),
                "warning": self.load_result.warning,
                "started": self._started,
            }

    def _status_for(
        self,
        schedule: Schedule,
        next_id: str,
        now: datetime,
        playing: dict[str, Any] | None,
    ) -> str:
        if not schedule.enabled:
            return "已停用"
        if playing and self._playing_schedule_id == schedule.id:
            return "播放中"
        if schedule.time_value <= now.time():
            return "已响"
        if schedule.id == next_id:
            return "待响"
        return "待响"

    # ------------------------------------------------------------------
    def add_schedule(self, fields: dict[str, Any]) -> Schedule:
        with self.lock:
            schedule = self._build_schedule(fields)
            self.data.schedules.append(schedule)
            self._save_locked()
            self.add_log(f"新增铃声 · {schedule.time} {schedule.name}", "ok")
            return schedule

    def update_schedule(self, schedule_id: str, fields: dict[str, Any]) -> Schedule:
        with self.lock:
            existing = self.data.find_schedule(schedule_id)
            if existing is None:
                raise KeyError("铃声不存在")
            schedule = self._build_schedule(fields, exclude_id=schedule_id)
            schedule.id = existing.id
            index = self.data.schedules.index(existing)
            self.data.schedules[index] = schedule
            if self._playing_schedule_id == schedule_id:
                self.player.stop()
                self._playing_schedule_id = ""
            self._save_locked()
            self.add_log(f"修改铃声 · {schedule.time} {schedule.name}", "info")
            return schedule

    def delete_schedule(self, schedule_id: str) -> None:
        with self.lock:
            schedule = self.data.find_schedule(schedule_id)
            if schedule is None:
                raise KeyError("铃声不存在")
            self.data.schedules = [
                s for s in self.data.schedules if s.id != schedule_id
            ]
            if self._playing_schedule_id == schedule_id:
                self.player.stop()
                self._playing_schedule_id = ""
            self._save_locked()
            self.add_log(f"删除铃声 · {schedule.time} {schedule.name}", "warn")

    def set_schedule_enabled(self, schedule_id: str, enabled: bool) -> Schedule:
        with self.lock:
            schedule = self.data.find_schedule(schedule_id)
            if schedule is None:
                raise KeyError("铃声不存在")
            schedule.enabled = bool(enabled)
            self._save_locked()
            self.add_log(
                f"{'启用' if enabled else '停用'}铃声 · {schedule.time} {schedule.name}",
                "info",
            )
            return schedule

    def clear_schedules(self) -> None:
        with self.lock:
            count = len(self.data.schedules)
            self.data.schedules = []
            self.player.stop()
            self._playing_schedule_id = ""
            self._save_locked()
            self.add_log(f"清空全部铃声（{count} 条）", "warn")

    def apply_template(self) -> list[Schedule]:
        with self.lock:
            if not self.data.audios:
                raise ValueError("音频库为空，无法套用示例作息")
            up = next(
                (a for a in self.data.audios if a.id == "builtin-up"),
                self.data.audios[0],
            )
            down = next(
                (a for a in self.data.audios if a.id == "builtin-down"),
                self.data.audios[-1],
            )
            self.data.schedules = seeded_schedules(up.id, down.id)
            self._save_locked()
            self.add_log(f"套用示例作息（{len(self.data.schedules)} 条）", "info")
            return self.data.schedules

    def _build_schedule(
        self,
        fields: dict[str, Any],
        exclude_id: str | None = None,
    ) -> Schedule:
        clock = str(fields.get("time") or "").strip()
        parse_time(clock)
        name = str(fields.get("name") or "").strip()
        if not name:
            raise ValueError("请填写铃声名称")
        audio_id = str(fields.get("audio_id") or "").strip()
        if self.data.find_audio(audio_id) is None:
            raise ValueError("请选择有效的音频")
        weekdays_raw = fields.get("weekdays") or []
        if not isinstance(weekdays_raw, list):
            raise ValueError("weekdays 必须是数组")
        weekdays: list[int] = []
        for item in weekdays_raw:
            try:
                day = int(item)
            except (TypeError, ValueError):
                raise ValueError(f"无效的星期值：{item}") from None
            if not 1 <= day <= 7:
                raise ValueError(f"星期范围必须是 1-7：{day}")
            if day not in weekdays:
                weekdays.append(day)
        weekdays.sort()
        if not weekdays:
            raise ValueError("请至少选择一个响铃星期")
        for other in self.data.schedules:
            if exclude_id and other.id == exclude_id:
                continue
            if not other.enabled:
                continue
            if other.time == clock and set(other.weekdays) & set(weekdays):
                raise ValueError(f"{clock} 已有「{other.name}」，相同星期不能重复")
        return Schedule(
            id=exclude_id or uuid.uuid4().hex[:12],
            time=clock,
            name=name[:60],
            audio_id=audio_id,
            weekdays=weekdays,
            enabled=bool(fields.get("enabled", True)),
        )

    # ------------------------------------------------------------------
    def preview_schedule(self, schedule_id: str) -> None:
        with self.lock:
            schedule = self.data.find_schedule(schedule_id)
            if schedule is None:
                raise KeyError("铃声不存在")
            self._play_schedule_locked(schedule, actual=False)

    def preview_audio(self, audio_id: str) -> None:
        with self.lock:
            asset = self.data.find_audio(audio_id)
            if asset is None:
                raise KeyError("音频不存在")
            path = self.storage.audio_path(asset)
            try:
                self.player.play(path, asset.name, asset.id)
            except PlayerError as exc:
                self.add_log(str(exc), "error")
                raise
            self._playing_schedule_id = ""
            self.add_log(f"试听音频：{asset.name}", "info")

    def stop_playback(self) -> None:
        with self.lock:
            self.player.stop()
            self._playing_schedule_id = ""
            self.add_log("已停止播放", "info")

    def set_settings(self, volume: int | None = None, paused: bool | None = None) -> Settings:
        with self.lock:
            if volume is not None:
                self.data.settings.volume = max(0, min(100, int(volume)))
                self.player.set_volume(self.data.settings.volume)
            if paused is not None:
                self.data.settings.paused = bool(paused)
            self._save_locked()
            self.add_log(
                f"设置已更新（音量 {self.data.settings.volume}%，"
                f"{'已暂停' if self.data.settings.paused else '运行中'}）",
                "info",
            )
            return self.data.settings

    # ------------------------------------------------------------------
    def add_audio_files(self, paths: Iterable[Path]) -> tuple[list[AudioAsset], list[str]]:
        with self.lock:
            added, errors = self.storage.import_audio_files(paths, self.data)
            if added:
                self._save_locked()
                self.add_log(f"导入 {len(added)} 个音频文件", "ok")
            if errors:
                self.add_log("部分音频导入失败：" + "；".join(errors[:3]), "warn")
            return added, errors

    def delete_audio(self, audio_id: str) -> None:
        with self.lock:
            asset = self.data.find_audio(audio_id)
            if asset is None:
                raise KeyError("音频不存在")
            if asset.builtin:
                raise ValueError("内置铃声不可删除")
            usage = sum(1 for s in self.data.schedules if s.audio_id == audio_id)
            if usage:
                raise ValueError(f"该音频仍被 {usage} 条铃声使用，无法删除")
            self.storage.delete_audio_file(asset)
            self.data.audios = [a for a in self.data.audios if a.id != audio_id]
            self._save_locked()
            self.add_log(f"删除音频 · {asset.name}", "warn")

    # ------------------------------------------------------------------
    def get_config_text(self) -> str:
        with self.lock:
            return self.storage.config_path.read_text(encoding="utf-8")

    def apply_config_text(self, content: str) -> AppData:
        try:
            raw = json.loads(content.lstrip("\ufeff"))
            parsed = self.storage.parse_config(raw, strict=True)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"配置有误：{exc}") from exc
        with self.lock:
            self.storage.save(parsed)
            self._replace_data_locked(parsed, stop=True)
            self.add_log("配置文件已保存并重新加载", "ok")
            return parsed

    def reload_config(self) -> AppData:
        try:
            parsed = self.storage.reload_strict()
        except (OSError, ValueError) as exc:
            raise ValueError(f"配置重载失败：{exc}") from exc
        with self.lock:
            self._replace_data_locked(parsed, stop=True)
            self.add_log("已从 config.json 重新加载配置", "ok")
            return parsed

    def export_bundle(self) -> Path:
        with self.lock:
            self.storage.backup_dir.mkdir(parents=True, exist_ok=True)
            target = self.storage.backup_dir / (
                f"export-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:5]}.zip"
            )
            self.storage.export_bundle(target, self.data)
            self.add_log(f"导出数据包 · {target.name}", "ok")
            return target

    def import_bundle(self, source: Path) -> ImportResult:
        with self.lock:
            result = self.storage.import_bundle(source, self.data)
            self._replace_data_locked(result.data, stop=True, save=False)
            self.add_log(
                f"导入数据包成功，原数据备份为 {result.backup_path.name}", "ok"
            )
            return result

    def _replace_data_locked(
        self,
        data: AppData,
        stop: bool = True,
        save: bool = False,
    ) -> None:
        if stop:
            self.player.stop()
            self._playing_schedule_id = ""
        if save:
            self.storage.save(data)
        self.data = data
        self._fired.clear()
        self._fired_day = ""
        self.player.set_volume(self.data.settings.volume)
        self.revision += 1

    def _save_locked(self) -> None:
        self.storage.save(self.data)
        self.revision += 1
