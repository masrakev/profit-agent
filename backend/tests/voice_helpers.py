"""WAV clips built in code, and a transcriber on the fake transport (no sleeping, spans kept)."""

import io
import math
import shutil
import struct
import subprocess
import wave
from array import array
from decimal import Decimal

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.llm import BudgetCaps, BudgetGuard, InMemorySpendLedger
from app.agent.llm.fake import FakeTransport, Step
from app.agent.llm.resilience import CircuitBreaker
from app.agent.llm.transcribe import MetaVoiceTranscriber, TranscribeRetryPolicy
from tests.llm_helpers import Clock


def wav(
    seconds: float = 1.0,
    *,
    rate: int = 16_000,
    channels: int = 1,
    width: int = 2,
    tone: bool = True,
) -> bytes:
    """A clip of a 440 Hz tone (or silence) in the given format."""
    frames = int(seconds * rate)
    peak = (1 << (8 * width - 1)) - 1
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(width)
        clip.setframerate(rate)
        if width == 2 and tone:
            second = [int(peak * 0.3 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate)]
            samples = array("h", (s for s in second for _ in range(channels)))
            whole, rest = divmod(frames, rate)
            clip.writeframes(samples.tobytes() * whole + samples[: rest * channels].tobytes())
        else:
            clip.writeframes((b"\x80" if width == 1 else b"\x00") * frames * channels * width)
    return buffer.getvalue()


def claimed_wav(seconds: int, rate: int = 16_000) -> bytes:
    """A WAV header claiming `seconds` of mono 16-bit audio, with almost no data after it."""
    size = seconds * rate * 2
    header = b"RIFF" + struct.pack("<I", 36 + size) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + b"data" + struct.pack("<I", size) + b"\x00" * 64


class VoiceHarness:
    def __init__(
        self,
        steps: list[Step] | None = None,
        *,
        caps: BudgetCaps | None = None,
        breaker: CircuitBreaker | None = None,
        transport_mode: str = "fake",
    ) -> None:
        self.transport = FakeTransport(steps or [])
        self.sleeps: list[float] = []
        self.exporter = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.guard = BudgetGuard(
            caps or BudgetCaps(Decimal("1.00"), Decimal("5.00")), InMemorySpendLedger()
        )
        self.clock = Clock()
        self.breaker = breaker or CircuitBreaker(clock=self.clock)
        self.transcriber = MetaVoiceTranscriber(
            api_key="test-key",
            transport=self.transport,
            budget=self.guard,
            transport_mode=transport_mode,
            retry=TranscribeRetryPolicy(sleep=self.sleeps.append),
            breaker=self.breaker,
            tracer_provider=tracer_provider,
        )


def encode(source: bytes, *args: str) -> bytes:
    """`source` (any format ffmpeg reads) re-encoded with `args`, through pipes."""
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "ffmpeg is needed (see the README)"
    done = subprocess.run(  # noqa: S603 - test helper, fixed arguments
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"],
        input=source,
        capture_output=True,
        check=True,
    )
    return done.stdout
