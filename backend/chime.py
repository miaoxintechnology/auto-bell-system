"""内置校园钟声合成。

不依赖任何第三方音频库：首次运行时用纯 Python 生成两段温暖、清晰的
钟声 WAV，保证软件开箱即用。
"""

from __future__ import annotations

import math
import shutil
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 44100

UP_FILENAME = "builtin_up.wav"
DOWN_FILENAME = "builtin_down.wav"


def _bell_note(frequency: float, duration: float) -> list[float]:
    """合成一个带泛音和指数衰减的钟声单音。"""
    count = int(SAMPLE_RATE * duration)
    partials = (
        (1.0, 1.00, 1.25),
        (2.0, 0.42, 1.75),
        (2.76, 0.23, 2.20),
        (3.0, 0.16, 2.65),
        (4.18, 0.09, 3.10),
        (5.43, 0.045, 3.60),
    )
    samples = [0.0] * count
    for ratio, amplitude, decay in partials:
        omega = 2.0 * math.pi * frequency * ratio / SAMPLE_RATE
        for index in range(count):
            t = index / SAMPLE_RATE
            attack = 1.0 - math.exp(-t * 140.0)
            envelope = attack * math.exp(-t * decay)
            # 高泛音衰减更快，声音更像真实金属钟。
            samples[index] += (
                amplitude
                * envelope
                * math.sin(omega * index + 0.12 * ratio)
            )
    return samples


def _mix_motif(
    notes: list[tuple[float, float, float]],
    total_seconds: float,
) -> list[float]:
    count = int(SAMPLE_RATE * total_seconds)
    buffer = [0.0] * count
    for start, frequency, duration in notes:
        voice = _bell_note(frequency, duration)
        offset = int(start * SAMPLE_RATE)
        limit = min(len(voice), count - offset)
        for index in range(limit):
            buffer[offset + index] += voice[index]
    return buffer


def _add_echo(buffer: list[float]) -> list[float]:
    """加入短延迟回声，让声音有一点礼堂空间感。"""
    output = list(buffer)
    for delay, gain in ((0.17, 0.20), (0.34, 0.09), (0.52, 0.045)):
        offset = int(delay * SAMPLE_RATE)
        for index in range(len(buffer) - offset):
            output[index + offset] += buffer[index] * gain
    return output


def _normalize_and_fade(buffer: list[float], peak: float = 0.80) -> list[float]:
    high = max((abs(value) for value in buffer), default=0.0)
    gain = (peak / high) if high > 0 else 0.0
    count = len(buffer)
    fade_in = int(0.008 * SAMPLE_RATE)
    fade_out = int(0.55 * SAMPLE_RATE)
    for index in range(count):
        factor = gain
        if index < fade_in:
            factor *= index / max(1, fade_in)
        remaining = count - index
        if remaining < fade_out:
            factor *= remaining / max(1, fade_out)
        buffer[index] *= factor
    return buffer


def _write_stereo(path: Path, mono: list[float]) -> None:
    """写出 16-bit 立体声 WAV，左右声道轻微错位以增加宽度。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    offset = int(0.006 * SAMPLE_RATE)
    pcm = array("h")
    for index, sample in enumerate(mono):
        right_index = index - offset
        right = mono[right_index] if right_index >= 0 else 0.0
        left_value = int(max(-1.0, min(1.0, sample)) * 32767)
        right_value = int(max(-1.0, min(1.0, right)) * 32767)
        pcm.append(left_value)
        pcm.append(right_value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())


def generate_up_chime(path: Path) -> None:
    """明亮的上课钟声：四音上行。"""
    notes = [
        (0.00, 523.25, 4.6),
        (0.52, 659.25, 4.4),
        (1.04, 783.99, 4.2),
        (1.56, 1046.50, 4.8),
        (1.62, 261.63, 3.8),
    ]
    audio = _mix_motif(notes, 8.2)
    _write_stereo(path, _normalize_and_fade(_add_echo(audio), 0.82))


def generate_down_chime(path: Path) -> None:
    """柔和的下课钟声：四音下行。"""
    notes = [
        (0.00, 783.99, 4.6),
        (0.58, 659.25, 4.5),
        (1.16, 523.25, 4.5),
        (1.74, 392.00, 5.0),
        (1.78, 196.00, 4.0),
    ]
    audio = _mix_motif(notes, 7.2)
    _write_stereo(path, _normalize_and_fade(_add_echo(audio), 0.72))


def ensure_builtin_chimes(
    audio_dir: Path,
    template_dir: Path | None = None,
) -> dict[str, Path]:
    """确保内置铃声存在，返回文件名到路径的映射。

    template_dir 指向随程序打包的音频模板；优先复制模板（瞬时完成），
    只有在模板缺失时才实时合成。
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    up = audio_dir / UP_FILENAME
    down = audio_dir / DOWN_FILENAME
    pairs = ((up, generate_up_chime), (down, generate_down_chime))
    for destination, generator in pairs:
        if destination.is_file() and destination.stat().st_size >= 1024:
            continue
        template = template_dir / destination.name if template_dir else None
        if template is not None and template.is_file():
            shutil.copy2(template, destination)
        else:
            generator(destination)
    return {UP_FILENAME: up, DOWN_FILENAME: down}
