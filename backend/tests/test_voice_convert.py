"""Recordings converted to WAV with ffmpeg (app/voice/convert.py): the formats owners record in
(Ogg/Opus from WhatsApp, WebM/Opus from Chrome, MP4/AAC from Safari, other PCM WAVs), the
whitelist, the limits checked before converting, the timeout, no shell, nothing left on disk."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from app.agent.llm.transcribe import inspect_wav
from app.voice import convert
from app.voice.audio import MAX_BYTES, ClipRejected
from app.voice.convert import Converter, prepare_clip, sniff
from bench.golden.checks import VOICE_DIR
from tests.voice_helpers import encode, wav

CONVERTER = Converter()
SOURCE = (VOICE_DIR / "goal_en.wav").read_bytes()
SOURCE_MS = inspect_wav(SOURCE).duration_ms


def fixture(name: str) -> bytes:
    return (VOICE_DIR / name).read_bytes()


def refused(audio: bytes, converter: Converter | None = CONVERTER) -> ClipRejected:
    with pytest.raises(ClipRejected) as caught:
        prepare_clip(audio, converter)
    return caught.value


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every process started: its arguments and options."""
    seen: list[dict[str, Any]] = []
    real = subprocess.run

    def run(args: Any, **kwargs: Any) -> Any:
        seen.append({"args": args, **kwargs})
        return real(args, **kwargs)

    monkeypatch.setattr(convert.subprocess, "run", run)
    return seen


def test_containers_are_recognised_by_their_signature() -> None:
    assert sniff(SOURCE) == "wav"
    assert sniff(fixture("goal_en.ogg")) == "ogg"
    assert sniff(fixture("goal_en.webm")) == "webm"
    assert sniff(fixture("goal_en.m4a")) == "mp4"
    assert sniff(b"ID3\x04 an mp3") is None
    assert sniff(b"") is None


@pytest.mark.parametrize(
    ("name", "label"),
    [("goal_en.ogg", "Ogg/Opus"), ("goal_en.webm", "WebM/Opus"), ("goal_en.m4a", "MP4/AAC")],
    ids=["whatsapp-ogg-opus", "chrome-webm-opus", "safari-mp4-aac"],
)
def test_recordings_are_converted_to_the_wav_the_endpoint_takes(
    name: str, label: str, calls: list[dict[str, Any]]
) -> None:
    converted, source = prepare_clip(fixture(name), CONVERTER)
    info = inspect_wav(converted)
    assert source == label
    assert info.sample_rate == 24_000
    assert abs(info.duration_ms - SOURCE_MS) < 250  # codec padding only
    probe, ffmpeg = calls
    for call in (probe, ffmpeg):
        args = call["args"]
        assert isinstance(args, list)  # no shell
        assert "shell" not in call
        assert args[args.index("-protocol_whitelist") + 1] == "file"
        assert args[args.index("-f") + 1] in ("ogg", "matroska", "mov")  # the demuxer forced
        assert call["timeout"] == CONVERTER.timeout_s
    assert ffmpeg["args"][ffmpeg["args"].index("-c:a") + 1] in ("opus", "aac")  # the decoder


def test_a_wav_the_endpoint_takes_is_sent_as_it_is(calls: list[dict[str, Any]]) -> None:
    assert prepare_clip(SOURCE, CONVERTER) == (SOURCE, "WAV")
    assert prepare_clip(SOURCE, None) == (SOURCE, "WAV")
    assert calls == []


def test_another_pcm_wav_is_converted() -> None:
    stereo = wav(2.0, rate=48_000, channels=2)
    converted, source = prepare_clip(stereo, CONVERTER)
    assert source == "WAV"
    assert (inspect_wav(converted).sample_rate, inspect_wav(converted).duration_ms) == (
        24_000,
        2000,
    )
    assert refused(stereo, None).code == "unsupported_audio"  # without a converter


@pytest.mark.parametrize(
    ("args", "detail"),
    [
        (("-c:a", "libmp3lame", "-f", "mp3"), "WAV, Ogg/Opus"),  # no signature it takes
        (("-c:a", "libvorbis", "-f", "ogg"), "Ogg/Opus, not vorbis"),
        (("-c:a", "flac", "-f", "matroska"), "WebM/Opus, not flac"),
        (("-c:a", "alac", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4"), "not alac"),
    ],
    ids=["mp3", "ogg-vorbis", "matroska-flac", "mp4-alac"],
)
def test_codecs_outside_the_whitelist_are_refused(args: tuple[str, ...], detail: str) -> None:
    rejection = refused(encode(SOURCE, *args))
    assert (rejection.status, rejection.code) == (415, "unsupported_audio")
    assert detail in rejection.message


def test_a_video_stream_is_refused() -> None:
    video = encode(
        SOURCE,
        "-f", "lavfi", "-i", "color=c=black:s=16x16:d=2",
        "-map", "1:v", "-map", "0:a", "-c:v", "mjpeg", "-c:a", "aac", "-shortest",
        "-movflags", "frag_keyframe+empty_moov", "-f", "mp4",
    )  # fmt: skip
    assert "one audio stream only" in refused(video).message


def test_a_stated_duration_over_two_minutes_is_refused_before_converting(
    calls: list[dict[str, Any]],
) -> None:
    long = encode(wav(125.0, tone=False), "-c:a", "libopus", "-b:a", "8k", "-f", "ogg")
    encoded = len(calls)  # the test's own encoding
    rejection = refused(long)
    assert (rejection.status, rejection.code) == (422, "audio_too_long")
    assert len(calls) - encoded == 1  # ffprobe only: nothing decoded


def test_an_unstated_duration_is_measured_after_converting() -> None:
    long = encode(wav(125.0, tone=False), "-c:a", "libopus", "-b:a", "8k", "-f", "webm")
    rejection = refused(long)
    assert (rejection.status, rejection.code) == (422, "audio_too_long")


def test_size_and_emptiness_are_checked_before_any_process(calls: list[dict[str, Any]]) -> None:
    assert refused(b"OggS" + b"\x00" * MAX_BYTES).status == 413
    assert refused(b"").code == "empty_audio"
    assert calls == []


def test_an_unreadable_recording_is_refused() -> None:
    rejection = refused(b"OggS" + bytes(range(256)) * 8)
    assert (rejection.status, rejection.code) == (415, "unsupported_audio")
    assert "Ogg/Opus" in rejection.message


def test_a_slow_conversion_is_stopped() -> None:
    rejection = refused(fixture("goal_en.ogg"), Converter(timeout_s=0.0001))
    assert (rejection.status, rejection.code) == (415, "unsupported_audio")
    assert "too long to read" in rejection.message


def test_without_ffmpeg_recordings_cannot_be_converted() -> None:
    rejection = refused(fixture("goal_en.ogg"), Converter(ffprobe="no-such-ffprobe"))
    assert (rejection.status, rejection.code) == (503, "conversion_unavailable")


def test_nothing_is_left_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    prepare_clip(fixture("goal_en.webm"), CONVERTER)
    refused(encode(SOURCE, "-c:a", "libvorbis", "-f", "ogg"))
    assert list(tmp_path.iterdir()) == []
