"""数据模型、时间计算与默认作息。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from .constants import WEEKDAY_NAMES

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def parse_time(value: str) -> time:
    """解析严格的 HH:MM 字符串。"""
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise ValueError(f"无效时间：{value!r}")
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def is_valid_time(value: str) -> bool:
    return isinstance(value, str) and bool(_TIME_RE.fullmatch(value))


def period_of_day(value: str) -> str:
    hour = int(value.split(":", 1)[0])
    if hour < 6:
        return "凌晨"
    if hour < 12:
        return "上午"
    if hour < 14:
        return "中午"
    if hour < 18:
        return "下午"
    return "晚上"


def format_weekdays(days: Iterable[int]) -> str:
    values = sorted({int(day) for day in days if 1 <= int(day) <= 7})
    if not values:
        return "未选择"
    if values == [1, 2, 3, 4, 5, 6, 7]:
        return "每天"
    if values == [1, 2, 3, 4, 5]:
        return "周一至周五"
    if values == [1, 2, 3, 4, 5, 6]:
        return "周一至周六"
    if values == [6, 7]:
        return "周六、周日"
    if (
        len(values) >= 3
        and values == list(range(values[0], values[-1] + 1))
    ):
        return f"{WEEKDAY_NAMES[values[0]]}至{WEEKDAY_NAMES[values[-1]]}"
    return "、".join(WEEKDAY_NAMES[day] for day in values)


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass
class AudioAsset:
    id: str
    name: str
    filename: str
    builtin: bool = False
    source_name: str = ""
    added_at: str = ""
    size_bytes: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AudioAsset":
        if not isinstance(raw, dict):
            raise ValueError("音频记录必须是对象")
        asset_id = str(raw.get("id") or "").strip()
        filename = str(raw.get("filename") or "").strip()
        if not asset_id or not filename:
            raise ValueError("音频记录缺少 id 或 filename")
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError("非法音频文件名")
        name = str(raw.get("name") or filename).strip() or filename
        return cls(
            id=asset_id,
            name=name[:80],
            filename=filename,
            builtin=as_bool(raw.get("builtin"), False),
            source_name=str(raw.get("source_name") or "")[:260],
            added_at=str(raw.get("added_at") or ""),
            size_bytes=max(0, int(raw.get("size_bytes") or 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "builtin": self.builtin,
            "source_name": self.source_name,
            "added_at": self.added_at,
            "size_bytes": self.size_bytes,
        }


@dataclass
class Schedule:
    id: str
    time: str
    name: str
    audio_id: str
    weekdays: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Schedule":
        if not isinstance(raw, dict):
            raise ValueError("铃声记录必须是对象")
        schedule_id = str(raw.get("id") or "").strip() or new_id()
        clock = str(raw.get("time") or "").strip()
        parse_time(clock)
        name = str(raw.get("name") or "").strip() or "未命名铃声"
        audio_id = str(raw.get("audio_id") or "").strip()
        weekdays_raw = raw.get("weekdays")
        if not isinstance(weekdays_raw, list):
            weekdays_raw = [1, 2, 3, 4, 5]
        weekdays: list[int] = []
        for item in weekdays_raw:
            try:
                day = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= day <= 7 and day not in weekdays:
                weekdays.append(day)
        if not weekdays:
            weekdays = [1, 2, 3, 4, 5]
        weekdays.sort()
        return cls(
            id=schedule_id,
            time=clock,
            name=name[:60],
            audio_id=audio_id,
            weekdays=weekdays,
            enabled=as_bool(raw.get("enabled"), True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "time": self.time,
            "name": self.name,
            "audio_id": self.audio_id,
            "weekdays": self.weekdays,
            "enabled": self.enabled,
        }

    @property
    def weekday_text(self) -> str:
        return format_weekdays(self.weekdays)

    @property
    def time_value(self) -> time:
        return parse_time(self.time)

    def occurs_on(self, day: date) -> bool:
        return day.isoweekday() in self.weekdays

    def occurrence_on(self, day: date) -> datetime | None:
        if not self.occurs_on(day):
            return None
        return datetime.combine(day, self.time_value)

    def next_occurrence(self, now: datetime) -> datetime | None:
        """严格晚于 now 的下一次响铃时间。"""
        for offset in range(0, 8):
            day = now.date() + timedelta(days=offset)
            target = self.occurrence_on(day)
            if target is not None and target > now:
                return target
        return None


@dataclass
class Settings:
    volume: int = 72
    paused: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        if not isinstance(raw, dict):
            return cls()
        try:
            volume = int(raw.get("volume", 72))
        except (TypeError, ValueError):
            volume = 72
        return cls(
            volume=max(0, min(100, volume)),
            paused=as_bool(raw.get("paused"), False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "volume": self.volume,
            "paused": self.paused,
        }


@dataclass
class AppData:
    version: int = 1
    audios: list[AudioAsset] = field(default_factory=list)
    schedules: list[Schedule] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def find_audio(self, audio_id: str) -> AudioAsset | None:
        for asset in self.audios:
            if asset.id == audio_id:
                return asset
        return None

    def find_schedule(self, schedule_id: str) -> Schedule | None:
        for item in self.schedules:
            if item.id == schedule_id:
                return item
        return None

    def sorted_schedules(self) -> list[Schedule]:
        return sorted(self.schedules, key=lambda item: (item.time, item.name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "audios": [item.to_dict() for item in self.audios],
            "schedules": [item.to_dict() for item in self.schedules],
            "settings": self.settings.to_dict(),
        }


def due_for(
    schedule: Schedule,
    now: datetime,
    tolerance_seconds: float = 2.0,
) -> datetime | None:
    """判断某条作息此刻是否应当响铃。

    只匹配当天、已启用且误差在 tolerance_seconds 以内的时刻，避免电脑休眠
    唤醒后补响一堆过期的铃声。
    """
    if not schedule.enabled:
        return None
    target = schedule.occurrence_on(now.date())
    if target is None:
        return None
    delta = (now - target).total_seconds()
    if 0 <= delta <= tolerance_seconds:
        return target
    return None


def next_bell(
    schedules: Iterable[Schedule],
    now: datetime,
) -> tuple[Schedule, datetime] | None:
    best: tuple[Schedule, datetime] | None = None
    for item in schedules:
        if not item.enabled:
            continue
        occurrence = item.next_occurrence(now)
        if occurrence is not None and (best is None or occurrence < best[1]):
            best = (item, occurrence)
    return best


def next_occurrence_for(schedule: Schedule, now: datetime) -> datetime | None:
    return schedule.next_occurrence(now)


def human_weekday(day: date) -> str:
    return WEEKDAY_NAMES.get(day.isoweekday(), "")


def human_date(day: date) -> str:
    return f"{day.year}年{day.month}月{day.day}日 {human_weekday(day)}"


def relative_day(target: datetime, now: datetime) -> str:
    """今天 / 明天 / 周三 这样的短标签。"""
    offset = (target.date() - now.date()).days
    if offset == 0:
        return "今天"
    if offset == 1:
        return "明天"
    if offset == 2:
        return "后天"
    return human_weekday(target.date())


def format_countdown(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    if days:
        return f"{days} 天 {hours:02d}:{minutes:02d}:{seconds:02d}"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def human_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def seeded_schedules(up_audio_id: str, down_audio_id: str) -> list[Schedule]:
    """首次运行时的一套可编辑示例作息。"""
    rows = [
        ("07:50", "预备铃", up_audio_id),
        ("08:00", "第一节课", up_audio_id),
        ("08:45", "第一节课下课", down_audio_id),
        ("08:55", "第二节课", up_audio_id),
        ("09:40", "第二节课下课", down_audio_id),
        ("10:00", "课间操结束", up_audio_id),
        ("10:10", "第三节课", up_audio_id),
        ("10:55", "第三节课下课", down_audio_id),
        ("11:05", "第四节课", up_audio_id),
        ("11:50", "上午放学", down_audio_id),
        ("14:10", "第五节课", up_audio_id),
        ("14:55", "第五节课下课", down_audio_id),
        ("15:05", "第六节课", up_audio_id),
        ("15:50", "第六节课下课", down_audio_id),
        ("16:00", "第七节课", up_audio_id),
        ("16:45", "放学铃", down_audio_id),
    ]
    return [
        Schedule(
            id=new_id(),
            time=clock,
            name=name,
            audio_id=audio_id,
            weekdays=[1, 2, 3, 4, 5],
            enabled=True,
        )
        for clock, name, audio_id in rows
    ]
