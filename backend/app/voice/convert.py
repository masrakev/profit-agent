"""Recordings in other formats, converted to the WAV the transcription endpoint takes (ADR 0026).

Browsers record WebM/Opus (Chrome, Firefox, Edge) or MP4/AAC (Safari); WhatsApp voice notes are
Ogg/Opus. Muse Voice Transcribe's file endpoint takes WAV only (`audioEncoding` is `enum('WAV')`,
checked on 2026-11-01; the realtime endpoint takes raw PCM). A WAV is sent as it is; the three
recorded formats, and a WAV the endpoint would refuse (stereo, 44.1 or 48 kHz, 24-bit or float
PCM, as some recorders write), are converted with ffmpeg, under these rules:

1. The size is checked first, before any process starts.
2. The container is recognised from the file's signature and its demuxer forced; ffprobe then
   lists its streams and duration. Exactly one stream, an audio one, whose codec is the one
   whitelisted for that container: Opus in Ogg and WebM, AAC in MP4, PCM in WAV. A duration the
   container
   states must be at most two minutes; a recording that states none (Chrome's WebM) is
   measured after conversion, which stops one second past the limit.
3. ffmpeg decodes that stream only, with the whitelisted decoder forced, dropping video,
   subtitles, data and metadata, to mono 16-bit PCM at 24 kHz (the model's native rate).
4. Both run from a list of arguments (no shell), read local files only
   (`-protocol_whitelist file`), use one thread and stop at a timeout. The recording sits in a
   private temporary directory deleted as soon as the conversion ends.

Any failure is the recording's (415), except a missing ffmpeg, which is the server's (503).
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.observability import get_logger
from app.voice.audio import MAX_BYTES, MAX_SECONDS, ClipRejected, check_clip

RATE = 24_000
ACCEPTED = "a WAV, Ogg/Opus, WebM/Opus or MP4/AAC recording"


@dataclass(frozen=True)
class Format:
    label: str
    demuxer: str
    codecs: dict[str, str]  # whitelisted codec -> the decoder forced for it


PCM = ("pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_u8")
FORMATS = {
    "wav": Format("WAV", "wav", {c: c for c in PCM}),  # one the endpoint refuses: stereo, 48 kHz
    "ogg": Format("Ogg/Opus", "ogg", {"opus": "opus"}),
    "webm": Format("WebM/Opus", "matroska", {"opus": "opus"}),
    "mp4": Format("MP4/AAC", "mov", {"aac": "aac"}),
}


def sniff(audio: bytes) -> str | None:
    """The container, from the file's signature: wav, ogg, webm, mp4, or None."""
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return "wav"
    if audio[:4] == b"OggS":
        return "ogg"
    if audio[:4] == b"\x1a\x45\xdf\xa3":  # EBML: Matroska, WebM
        return "webm"
    if audio[4:8] == b"ftyp":
        return "mp4"
    return None


def _seconds(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None  # "N/A": the container states no duration


@dataclass(frozen=True)
class Converter:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    timeout_s: float = 20.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "Converter":
        return cls(settings.voice_ffmpeg, settings.voice_ffprobe, settings.voice_convert_timeout_s)

    def to_wav(self, audio: bytes, kind: str) -> bytes:
        fmt = FORMATS[kind]
        ffprobe, ffmpeg = self._tool(self.ffprobe), self._tool(self.ffmpeg)
        with tempfile.TemporaryDirectory(prefix="voice-") as tmp:
            source, target = Path(tmp) / f"in.{kind}", Path(tmp) / "out.wav"
            source.write_bytes(audio)
            probed = self._run(
                fmt,
                ffprobe,
                "-v", "error", "-hide_banner", "-protocol_whitelist", "file",
                "-f", fmt.demuxer,
                "-show_entries", "format=duration:stream=codec_type,codec_name",
                "-of", "json",
                str(source),
            )  # fmt: skip
            codec = self._checked(fmt, probed)
            self._run(
                fmt,
                ffmpeg,
                "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
                "-protocol_whitelist", "file",
                "-f", fmt.demuxer, "-c:a", fmt.codecs[codec], "-i", str(source),
                "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1",
                "-t", str(MAX_SECONDS + 1),
                "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le",
                "-fflags", "+bitexact", "-flags:a", "+bitexact",
                "-f", "wav", str(target),
            )  # fmt: skip
            return target.read_bytes()

    def _checked(self, fmt: Format, probed: bytes) -> str:
        try:
            info = json.loads(probed)
        except json.JSONDecodeError as exc:
            raise ClipRejected(415, "unsupported_audio", f"not a {fmt.label} recording") from exc
        streams = info.get("streams") or []
        if len(streams) != 1 or streams[0].get("codec_type") != "audio":
            raise ClipRejected(
                415, "unsupported_audio", f"a {fmt.label} recording holds one audio stream only"
            )
        codec = str(streams[0].get("codec_name"))
        if codec not in fmt.codecs:
            raise ClipRejected(415, "unsupported_audio", f"{fmt.label}, not {codec}")
        duration = _seconds((info.get("format") or {}).get("duration"))
        if duration is not None and duration > MAX_SECONDS:
            raise ClipRejected(
                422, "audio_too_long", f"a recording of at most {MAX_SECONDS} seconds"
            )
        return codec

    @staticmethod
    def _tool(name: str) -> str:
        found = shutil.which(name)
        if found is None:
            raise ClipRejected(503, "conversion_unavailable", "recordings cannot be converted")
        return found

    def _run(self, fmt: Format, *args: str) -> bytes:
        try:
            done = subprocess.run(  # noqa: S603 - fixed arguments, no shell, local files only
                list(args),
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClipRejected(
                415, "unsupported_audio", f"the {fmt.label} recording took too long to read"
            ) from exc
        if done.returncode != 0:
            get_logger(__name__).info(
                "voice.conversion_failed",
                format=fmt.label,
                error=done.stderr[-300:].decode("utf-8", "replace"),
            )
            raise ClipRejected(415, "unsupported_audio", f"not a readable {fmt.label} recording")
        return done.stdout


def prepare_clip(audio: bytes, converter: Converter | None) -> tuple[bytes, str]:
    """The recording as a WAV the endpoint takes, and the format it came in: a WAV the endpoint
    takes as it is; Ogg/Opus, WebM/Opus, MP4/AAC or another PCM WAV converted; anything else
    refused (415). Size first, then format and duration, then conversion."""
    if not audio:
        raise ClipRejected(422, "empty_audio", "the recording is empty")
    if len(audio) > MAX_BYTES:
        raise ClipRejected(413, "audio_too_large", f"a recording of at most {MAX_BYTES} bytes")
    kind = sniff(audio)
    if kind == "wav":
        try:
            check_clip(audio)
            return audio, "WAV"
        except ClipRejected as exc:
            if exc.status != 415 or converter is None:
                raise
    if kind is None or converter is None:
        raise ClipRejected(415, "unsupported_audio", ACCEPTED)
    wav = converter.to_wav(audio, kind)
    check_clip(wav)
    return wav, FORMATS[kind].label
