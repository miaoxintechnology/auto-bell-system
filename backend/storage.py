"""配置、音频文件和首次运行初始化。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable

from .chime import ensure_builtin_chimes
from .constants import APP_VERSION, MAX_AUDIO_BYTES, SUPPORTED_AUDIO_EXTENSIONS
from .models import (
    AppData,
    AudioAsset,
    Schedule,
    Settings,
    new_id,
    parse_time,
)
from .paths import asset_path, default_data_dir


@dataclass
class LoadResult:
    data: AppData
    warning: str = ""
    created: bool = False


@dataclass
class ImportResult:
    data: AppData
    backup_path: Path
    missing_audio: list[str]


class Storage:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or default_data_dir()).expanduser().resolve()
        self.audio_dir = self.base_dir / "audio"
        self.log_dir = self.base_dir / "logs"
        self.backup_dir = self.base_dir / "backups"
        self.config_path = self.base_dir / "config.json"

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def audio_path(self, asset: AudioAsset) -> Path:
        return self.audio_dir / asset.filename

    def bootstrap(self) -> LoadResult:
        self.ensure_dirs()
        ensure_builtin_chimes(self.audio_dir, asset_path("audio"))
        if self.config_path.is_file():
            return self._load_existing()
        data = self._default_data()
        self.save(data)
        return LoadResult(data, created=True)

    def _default_data(self) -> AppData:
        up = self.audio_dir / "builtin_up.wav"
        down = self.audio_dir / "builtin_down.wav"
        now = datetime.now().isoformat(timespec="seconds")
        audios = [
            AudioAsset(
                id="builtin-up",
                name="标准上课铃",
                filename=up.name,
                builtin=True,
                source_name="内置合成钟声",
                added_at=now,
                size_bytes=up.stat().st_size if up.exists() else 0,
            ),
            AudioAsset(
                id="builtin-down",
                name="标准下课铃",
                filename=down.name,
                builtin=True,
                source_name="内置合成钟声",
                added_at=now,
                size_bytes=down.stat().st_size if down.exists() else 0,
            ),
        ]
        return AppData(
            version=1,
            audios=audios,
            schedules=[],
            settings=Settings(),
        )

    def _load_existing(self) -> LoadResult:
        warning = ""
        try:
            raw = json.loads(
                self.config_path.read_text(encoding="utf-8-sig")
            )
            if not isinstance(raw, dict):
                raise ValueError("配置文件根节点不是对象")
            data = self._from_dict(raw)
        except Exception as exc:  # noqa: BLE001 - 配置容错需要兜底
            backup = self.base_dir / (
                f"config.broken-{datetime.now():%Y%m%d-%H%M%S}.json"
            )
            try:
                shutil.copy2(self.config_path, backup)
            except OSError:
                backup = Path()
            data = self._default_data()
            self.save(data)
            warning = f"配置文件无法读取，已恢复默认设置（{exc}）"
            if backup:
                warning += f"，原文件备份为 {backup.name}"
        return LoadResult(data, warning)

    def reload_strict(self) -> AppData:
        """从 config.json 严格重载；任何字段错误都抛出 ValueError。

        用于“重新加载配置文件”按钮，避免把用户手工写坏的配置悄悄重置。
        """
        if not self.config_path.is_file():
            raise FileNotFoundError(f"配置文件不存在：{self.config_path}")
        try:
            raw = json.loads(
                self.config_path.read_text(encoding="utf-8-sig")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON 格式错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}"
            ) from exc
        if not isinstance(raw, dict):
            raise ValueError("配置文件根节点必须是 JSON 对象")
        return self._from_dict(raw, strict=True)

    def parse_config(self, raw: dict, strict: bool = True) -> AppData:
        return self._from_dict(raw, strict=strict)

    def _from_dict(
        self,
        raw: dict,
        audio_root: Path | None = None,
        strict: bool = False,
    ) -> AppData:
        if not isinstance(raw, dict):
            raise ValueError("config.json 根节点必须是 JSON 对象")
        audios_raw = raw.get("audios", [])
        schedules_raw = raw.get("schedules", [])
        if not isinstance(audios_raw, list):
            raise ValueError("audios 必须是数组")
        if not isinstance(schedules_raw, list):
            raise ValueError("schedules 必须是数组")
        settings_raw = raw.get("settings") or {}
        if strict and not isinstance(settings_raw, dict):
            raise ValueError("settings 必须是对象")
        settings = Settings.from_dict(settings_raw)
        audio_root = audio_root or self.audio_dir
        audios: list[AudioAsset] = []
        seen_audio_ids: set[str] = set()
        seen_filenames: set[str] = set()
        for index, item in enumerate(audios_raw, start=1):
            try:
                asset = AudioAsset.from_dict(item)
            except (ValueError, TypeError) as exc:
                if strict:
                    raise ValueError(f"第 {index} 个音频配置无效：{exc}") from exc
                continue
            if asset.id in seen_audio_ids:
                if strict:
                    raise ValueError(f"第 {index} 个音频的 id 重复：{asset.id}")
                asset.id = new_id()
            if asset.filename.lower() in seen_filenames:
                if strict:
                    raise ValueError(
                        f"第 {index} 个音频的文件名重复：{asset.filename}"
                    )
                continue
            # 文件被手动删除时仍保留记录，界面上会提示缺失。
            path = audio_root / asset.filename
            if path.is_file():
                asset.size_bytes = path.stat().st_size
            seen_audio_ids.add(asset.id)
            seen_filenames.add(asset.filename.lower())
            audios.append(asset)

        schedules: list[Schedule] = []
        seen_schedule_ids: set[str] = set()
        for index, item in enumerate(schedules_raw, start=1):
            try:
                schedule = Schedule.from_dict(item)
                parse_time(schedule.time)
            except (ValueError, TypeError) as exc:
                if strict:
                    raise ValueError(f"第 {index} 条铃声配置无效：{exc}") from exc
                continue
            if schedule.id in seen_schedule_ids:
                if strict:
                    raise ValueError(f"第 {index} 条铃声的 id 重复：{schedule.id}")
                schedule.id = new_id()
            if schedule.audio_id not in seen_audio_ids:
                if strict:
                    raise ValueError(
                        f"第 {index} 条铃声引用了不存在的音频 id：{schedule.audio_id or '（空）'}"
                    )
            seen_schedule_ids.add(schedule.id)
            schedules.append(schedule)

        return AppData(
            version=1,
            audios=audios,
            schedules=schedules,
            settings=settings,
        )

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def save(self, data: AppData) -> None:
        self.ensure_dirs()
        payload = json.dumps(data.to_dict(), ensure_ascii=False, indent=2)
        temp = self.config_path.with_suffix(".json.tmp")
        temp.write_text(payload + "\n", encoding="utf-8")
        if self.config_path.is_file():
            try:
                shutil.copy2(self.config_path, self.config_path.with_suffix(".json.bak"))
            except OSError:
                pass
        os.replace(temp, self.config_path)

    # ------------------------------------------------------------------
    # 数据包导入 / 导出
    # ------------------------------------------------------------------
    def export_bundle(self, destination: Path, data: AppData) -> Path:
        """导出配置 + 音频库为 ZIP 数据包。"""
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_dirs()
        missing = [
            asset.name
            for asset in data.audios
            if not self.audio_path(asset).is_file()
        ]
        manifest = {
            "format": "autobell-data",
            "format_version": 1,
            "app_version": APP_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "schedule_count": len(data.schedules),
            "audio_count": len(data.audios),
            "missing_audio": missing,
        }
        temporary = destination.with_name(
            f"{destination.name}.{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                )
                archive.writestr(
                    "config.json",
                    json.dumps(data.to_dict(), ensure_ascii=False, indent=2)
                    + "\n",
                )
                archive.writestr(
                    "README.txt",
                    "自动铃声系统数据包\n"
                    "包含 config.json 和 audio/ 音频文件。\n"
                    "请通过软件「设置 → 数据转移 → 导入数据包」恢复，"
                    "不要直接解压覆盖正在使用的数据目录。\n",
                )
                for asset in data.audios:
                    source = self.audio_path(asset)
                    if source.is_file():
                        archive.write(source, f"audio/{asset.filename}")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def import_bundle(self, source: Path, current_data: AppData) -> ImportResult:
        """校验并导入数据包；导入前自动备份，失败时回滚音频目录。"""
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"数据包不存在：{source}")
        if source.suffix.lower() != ".zip":
            raise ValueError("请选择 .zip 格式的数据包")
        self.ensure_dirs()
        temp_root = Path(
            tempfile.mkdtemp(prefix="import-", dir=str(self.base_dir))
        )
        temp_audio = temp_root / "audio"
        temp_audio.mkdir(parents=True, exist_ok=True)
        try:
            try:
                archive = zipfile.ZipFile(source, "r")
            except zipfile.BadZipFile as exc:
                raise ValueError("文件不是有效的 ZIP 数据包") from exc
            with archive:
                broken = archive.testzip()
                if broken:
                    raise ValueError(f"数据包损坏：{broken}")
                names: set[str] = set()
                for info in archive.infolist():
                    normalized = info.filename.replace("\\", "/")
                    parts = PurePosixPath(normalized).parts
                    if normalized.startswith("/") or ".." in parts:
                        raise ValueError(f"数据包包含非法路径：{info.filename}")
                    names.add(normalized)
                if "manifest.json" not in names or "config.json" not in names:
                    raise ValueError("数据包缺少 manifest.json 或 config.json")
                try:
                    manifest = json.loads(
                        archive.read("manifest.json").decode("utf-8-sig")
                    )
                except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("数据包 manifest.json 无法读取") from exc
                if not isinstance(manifest, dict) or manifest.get(
                    "format"
                ) != "autobell-data":
                    raise ValueError("不是自动铃声系统生成的数据包")
                try:
                    version = int(manifest.get("format_version", 0))
                except (TypeError, ValueError):
                    version = 0
                if version != 1:
                    raise ValueError(f"不支持的数据包版本：{version}")
                try:
                    raw = json.loads(
                        archive.read("config.json").decode("utf-8-sig")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"数据包中的 config.json 格式错误：{exc}") from exc
                data = self._from_dict(
                    raw,
                    audio_root=temp_audio,
                    strict=True,
                )
                missing: list[str] = []
                for asset in data.audios:
                    member = f"audio/{asset.filename}"
                    if member not in names:
                        missing.append(asset.name)
                        continue
                    target = temp_audio / asset.filename
                    with archive.open(member) as source_file, target.open(
                        "wb"
                    ) as target_file:
                        shutil.copyfileobj(source_file, target_file)
                    size = target.stat().st_size
                    if size <= 0:
                        raise ValueError(f"音频文件为空：{asset.name}")
                    if size > MAX_AUDIO_BYTES:
                        raise ValueError(f"音频文件超过 300 MB：{asset.name}")
                    asset.size_bytes = size
            ensure_builtin_chimes(temp_audio, asset_path("audio"))
            for asset in data.audios:
                path = temp_audio / asset.filename
                if not path.is_file():
                    if asset.name not in missing:
                        missing.append(asset.name)
                else:
                    asset.size_bytes = path.stat().st_size
            if missing:
                raise ValueError("数据包缺少音频文件：" + "、".join(missing[:8]))

            self.backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = self.backup_dir / (
                f"before-import-{datetime.now():%Y%m%d-%H%M%S}-"
                f"{uuid.uuid4().hex[:6]}.zip"
            )
            try:
                self.export_bundle(backup_path, current_data)
            except OSError as exc:
                raise OSError(f"无法创建导入前的自动备份：{exc}") from exc

            old_audio = self.base_dir / (
                f"audio.old-{datetime.now():%Y%m%d-%H%M%S}-"
                f"{uuid.uuid4().hex[:6]}"
            )
            had_audio = self.audio_dir.exists()
            if had_audio:
                os.replace(self.audio_dir, old_audio)
            try:
                os.replace(temp_audio, self.audio_dir)
                self.save(data)
            except Exception:
                if self.audio_dir.exists():
                    shutil.rmtree(self.audio_dir, ignore_errors=True)
                if had_audio and old_audio.exists():
                    os.replace(old_audio, self.audio_dir)
                raise
            else:
                if old_audio.exists():
                    shutil.rmtree(old_audio, ignore_errors=True)
            return ImportResult(data=data, backup_path=backup_path, missing_audio=[])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    # ------------------------------------------------------------------
    # 音频
    # ------------------------------------------------------------------
    def import_audio_files(
        self,
        paths: Iterable[str | Path],
        data: AppData,
    ) -> tuple[list[AudioAsset], list[str]]:
        """复制音频到应用数据目录，返回成功项和错误信息。"""
        self.ensure_dirs()
        added: list[AudioAsset] = []
        errors: list[str] = []
        existing_names = {asset.name.casefold() for asset in data.audios}
        for raw_path in paths:
            path = Path(raw_path)
            suffix = path.suffix.lower()
            if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
                errors.append(f"{path.name}：不支持的格式 {suffix or '（无扩展名）'}")
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                errors.append(f"{path.name}：无法读取（{exc}）")
                continue
            if size <= 0:
                errors.append(f"{path.name}：文件为空")
                continue
            if size > MAX_AUDIO_BYTES:
                errors.append(f"{path.name}：文件超过 300 MB")
                continue
            filename = f"{uuid.uuid4().hex}{suffix}"
            destination = self.audio_dir / filename
            try:
                shutil.copy2(path, destination)
            except OSError as exc:
                errors.append(f"{path.name}：复制失败（{exc}）")
                continue
            display = path.stem.strip()[:60] or "未命名音频"
            candidate = display
            index = 2
            while candidate.casefold() in existing_names:
                candidate = f"{display} ({index})"
                index += 1
            existing_names.add(candidate.casefold())
            asset = AudioAsset(
                id=new_id(),
                name=candidate,
                filename=filename,
                builtin=False,
                source_name=str(path)[:260],
                added_at=datetime.now().isoformat(timespec="seconds"),
                size_bytes=size,
            )
            data.audios.append(asset)
            added.append(asset)
        return added, errors

    def delete_audio_file(self, asset: AudioAsset) -> None:
        if asset.builtin:
            raise ValueError("内置铃声不可删除")
        path = self.audio_path(asset)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise OSError(f"删除音频文件失败：{exc}") from exc

    def usage_count(self, data: AppData, audio_id: str) -> int:
        return sum(1 for item in data.schedules if item.audio_id == audio_id)
