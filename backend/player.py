"""后端音频播放：使用 pygame/SDL_mixer。"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402


class PlayerError(RuntimeError):
    pass


class AudioPlayer:
    """单通道播放器；铃声之间会互相打断。"""

    def __init__(self, volume: int = 72) -> None:
        self._lock = threading.RLock()
        self._volume = max(0, min(100, int(volume)))
        self._initialized = False
        self._sound: pygame.mixer.Sound | None = None
        self._label = ""
        self._audio_id = ""
        self._started_at = 0.0

    def _ensure_initialized(self) -> None:
        if self._initialized and pygame.mixer.get_init():
            return
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        except Exception as exc:  # noqa: BLE001
            raise PlayerError(f"音频设备初始化失败：{exc}") from exc
        self._initialized = True

    def set_volume(self, volume: int) -> None:
        with self._lock:
            self._volume = max(0, min(100, int(volume)))
            if self._sound is not None:
                self._sound.set_volume(self._volume / 100.0)

    @property
    def volume(self) -> int:
        return self._volume

    def play(self, path: Path | str, label: str, audio_id: str) -> None:
        target = Path(path)
        if not target.is_file():
            raise PlayerError(f"找不到音频文件：{target.name}")
        with self._lock:
            self._ensure_initialized()
            try:
                pygame.mixer.stop()
                sound = pygame.mixer.Sound(str(target))
                sound.set_volume(self._volume / 100.0)
                channel = sound.play()
            except Exception as exc:  # noqa: BLE001
                raise PlayerError(f"无法播放音频：{exc}") from exc
            if channel is None:
                raise PlayerError("音频通道不可用")
            self._sound = sound
            self._label = label
            self._audio_id = audio_id
            self._started_at = time.monotonic()

    def stop(self) -> None:
        with self._lock:
            try:
                pygame.mixer.stop()
            except Exception:  # noqa: BLE001
                pass
            self._sound = None
            self._label = ""
            self._audio_id = ""
            self._started_at = 0.0

    def is_playing(self) -> bool:
        with self._lock:
            if self._sound is None:
                return False
            try:
                busy = bool(pygame.mixer.get_busy())
            except Exception:  # noqa: BLE001
                busy = False
            if not busy:
                self._sound = None
                self._label = ""
                self._audio_id = ""
                self._started_at = 0.0
            return busy

    def status(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.is_playing():
                return None
            return {
                "label": self._label,
                "audio_id": self._audio_id,
                "elapsed": round(time.monotonic() - self._started_at, 1),
            }

    def shutdown(self) -> None:
        self.stop()
        with self._lock:
            if self._initialized:
                try:
                    pygame.mixer.quit()
                except Exception:  # noqa: BLE001
                    pass
                self._initialized = False
