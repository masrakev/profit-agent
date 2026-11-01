"""Muse Voice Transcribe behind the model layer's guards (app/agent/llm/transcribe.py): the
documented request, cost in whole seconds, budget, retries, circuit breaker, trace span, and
record / replay of multipart uploads keyed by the audio's hash."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.agent.llm import BudgetCaps, DataOrigin
from app.agent.llm import fake as f
from app.agent.llm.cassette import CassetteStore, LLMMode, multipart_body
from app.agent.llm.errors import (
    AuthenticationFailedError,
    BudgetExceededError,
    CassetteMissError,
    CircuitOpenError,
    InvalidRequestError,
    LLMConnectionError,
    LLMTimeoutError,
    ProviderUnavailableError,
    RateLimitedError,
    RecordingForbiddenError,
    ResponseFormatError,
)
from app.agent.llm.factory import build_transcriber
from app.agent.llm.models import AudioModelId, load_prices
from app.agent.llm.resilience import BreakerState, CircuitBreaker
from app.agent.llm.transcribe import (
    TranscribeRetryPolicy,
    TranscriptionRequest,
    inspect_wav,
    parse_transcription,
)
from app.config import Settings
from tests.voice_helpers import VoiceHarness, claimed_wav, wav

D = Decimal
VOICE = AudioModelId.VOICE_TRANSCRIBE


def request(audio: bytes | None = None, **overrides: object) -> TranscriptionRequest:
    fields: dict[str, object] = {
        "audio": audio if audio is not None else wav(10.5),
        "data_origin": DataOrigin.REAL,
        "run_id": "run-1",
    }
    fields.update(overrides)
    return TranscriptionRequest(**fields)  # type: ignore[arg-type]


# --- price ---------------------------------------------------------------------------------


def test_audio_cost_golden() -> None:
    table = load_prices()
    assert (table.version, str(table.verified_on)) == (2, "2026-11-01")
    assert table.audio[VOICE].per_hour == D("0.18")
    # 0.18 USD an hour is 0.00005 USD a second.
    assert table.audio_cost(VOICE, 3600) == D("0.18")
    assert table.audio_cost(VOICE, 10) == D("0.0005")
    assert table.audio_cost(VOICE, 1) == D("0.00005")
    assert table.audio_cost(VOICE, 0) == 0
    with pytest.raises(ValueError, match="negative"):
        table.audio_cost(VOICE, -1)


def test_an_audio_price_must_be_standard_and_present(tmp_path: Path) -> None:
    from app.agent.llm.models import PRICES_FILE

    text = PRICES_FILE.read_text(encoding="utf-8")
    contributor = tmp_path / "contributor.toml"
    contributor.write_text(
        text.replace(
            'id = "muse-voice-transcribe-1.0"\nmode = "standard"',
            'id = "muse-voice-transcribe-1.0"\nmode = "contributor"',
        )
    )
    with pytest.raises(ValueError, match="audio is Standard"):
        load_prices.__wrapped__(contributor)
    missing = tmp_path / "missing.toml"
    missing.write_text(text.split("[audio.")[0])
    with pytest.raises(ValueError, match="misses"):
        load_prices.__wrapped__(missing)


# --- the call ------------------------------------------------------------------------------


def test_a_clip_is_transcribed_and_billed_in_whole_seconds() -> None:
    h = VoiceHarness([f.transcription("What was my profit last week?", 10_999)])
    audio = wav(11.0)
    keywords = ("Blue mug", "", "x" * 60)
    done = h.transcriber.transcribe(request(audio, keywords=keywords, session_id="voice-1"))
    assert done.transcript == "What was my profit last week?"
    assert (done.audio_duration_ms, done.billed_seconds) == (10_999, 10)  # rounded down
    assert done.cost_usd == D("0.0005")
    assert (done.model, done.attempts, done.session_id) == (VOICE.value, 1, "fake-session")
    sent = h.transport.requests[0]
    assert sent["request"] == {
        "model": "muse-voice-transcribe-1.0",
        "audioEncoding": "WAV",
        "mode": "PUSH_TO_TALK",
        "keywords": ["Blue mug", "x" * 40],  # blank dropped, long ones cut
    }
    assert sent["audio"] == {
        "sha256": hashlib.sha256(audio).hexdigest(),
        "bytes": len(audio),
        "type": "audio/wav",
    }
    headers = h.transport.headers[0]
    assert headers["authorization"] == "Bearer test-key"
    assert headers["accept"] == "application/json"
    assert h.guard.spent("run-1").run == D("0.0005")  # the reservation settled to the cost
    (span,) = h.exporter.get_finished_spans()
    assert span.name == "voice.transcribe"
    attrs = dict(span.attributes or {})
    assert attrs["voice.billed_seconds"] == 10
    assert attrs["llm.cost_usd"] == "0.0005"
    assert attrs["llm.outcome"] == "ok"
    assert attrs["voice.keywords"] == 3
    assert "Blue mug" not in json.dumps({k: str(v) for k, v in attrs.items()})


def test_language_bias_is_sent_when_given() -> None:
    h = VoiceHarness([f.transcription("Bonjour")])
    h.transcriber.transcribe(request(wav(1.0), language_bias=("French", "English")))
    assert h.transport.requests[0]["request"]["languageBias"] == ["French", "English"]
    assert "keywords" not in h.transport.requests[0]["request"]


def test_too_many_keywords_are_refused() -> None:
    with pytest.raises(ValidationError):
        request(keywords=tuple(f"name {i}" for i in range(51)))


@pytest.mark.parametrize(
    ("audio", "match"),
    [
        (b"not audio", "not a PCM WAV"),
        (wav(1.0, channels=2), "mono 16-bit"),
        (wav(1.0, width=1), "mono 16-bit"),
        (wav(1.0, rate=44_100), "44100 Hz"),
        (claimed_wav(11 * 60), "limits"),
    ],
    ids=["not-wav", "stereo", "8-bit", "44.1kHz", "over-10-minutes"],
)
def test_audio_the_endpoint_refuses_is_never_sent(audio: bytes, match: str) -> None:
    h = VoiceHarness([])
    with pytest.raises(InvalidRequestError, match=match):
        h.transcriber.transcribe(request(audio))
    assert h.transport.requests == []
    assert h.guard.spent("run-1").run == 0


def test_both_documented_sample_rates_are_accepted() -> None:
    assert inspect_wav(wav(2.0, rate=24_000)).duration_ms == 2000
    assert inspect_wav(wav(0.5)).duration_ms == 500


def test_the_budget_refuses_before_calling() -> None:
    h = VoiceHarness([], caps=BudgetCaps(D("0.0001"), D("5.00")))
    with pytest.raises(BudgetExceededError):
        h.transcriber.transcribe(request(wav(10.0)))  # up to 0.0005 USD
    assert h.transport.requests == []


def test_a_rate_limit_is_retried_with_backoff_and_not_billed() -> None:
    h = VoiceHarness([f.rate_limited(retry_after=2.0), f.transcription("ok", 1_000)])
    done = h.transcriber.transcribe(request(wav(1.0)))
    assert (done.attempts, done.billed_seconds) == (2, 1)
    assert h.sleeps[0] >= 2.0
    assert h.guard.spent("run-1").run == D("0.00005")
    h = VoiceHarness([f.rate_limited(None)] * 4)
    with pytest.raises(RateLimitedError):
        h.transcriber.transcribe(request(wav(1.0)))
    assert len(h.transport.requests) == 4
    assert h.guard.spent("run-1").run == 0


def test_a_server_error_is_retried_once() -> None:
    server_error = f.error(500, "server_error", "Transcription failed")
    h = VoiceHarness([server_error, server_error, f.transcription("never")])
    with pytest.raises(ProviderUnavailableError, match="HTTP 500"):
        h.transcriber.transcribe(request(wav(1.0)))
    assert len(h.transport.requests) == 2
    assert h.transport.remaining == 1
    h = VoiceHarness([server_error, f.transcription("second time", 1_000)])
    assert h.transcriber.transcribe(request(wav(1.0))).transcript == "second time"


def test_network_failures_are_retried() -> None:
    h = VoiceHarness(
        [f.Raise(httpx2.ReadTimeout), f.Raise(httpx2.ConnectError), f.transcription("ok")]
    )
    assert h.transcriber.transcribe(request(wav(1.0))).attempts == 3
    h = VoiceHarness([f.Raise(httpx2.ReadTimeout)] * 4)
    with pytest.raises(LLMTimeoutError):
        h.transcriber.transcribe(request(wav(1.0)))
    h = VoiceHarness([f.Raise(httpx2.ConnectError)] * 4)
    with pytest.raises(LLMConnectionError):
        h.transcriber.transcribe(request(wav(1.0)))


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (
            f.error(400, "invalid_request_error", "Audio exceeds 10 minutes", code="audio"),
            InvalidRequestError,
        ),
        (f.error(413, "invalid_request_error", "Too large"), InvalidRequestError),
        (f.Reply(406, None), InvalidRequestError),
        (f.error(401, "authentication_error", "Bad key"), AuthenticationFailedError),
    ],
)
def test_client_errors_are_not_retried(reply: f.Reply, error: type[Exception]) -> None:
    h = VoiceHarness([reply, f.transcription("never")])
    with pytest.raises(error):
        h.transcriber.transcribe(request(wav(1.0)))
    assert len(h.transport.requests) == 1


def test_an_unexpected_answer_fails_loudly_and_keeps_the_reservation() -> None:
    h = VoiceHarness([f.Reply(200, {"text": "no transcript field"})])
    with pytest.raises(ResponseFormatError):
        h.transcriber.transcribe(request(wav(2.0)))
    assert h.guard.spent("run-1").run == D("0.0001")  # two seconds: billing unknown
    with pytest.raises(ResponseFormatError, match="not JSON"):
        parse_transcription(b"<html>")
    span = h.exporter.get_finished_spans()[0]
    assert dict(span.attributes or {})["llm.outcome"] == "ResponseFormatError"


def test_the_circuit_opens_after_repeated_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown=30.0)
    server_error = f.error(503, "server_error", "Overloaded")
    h = VoiceHarness([server_error, server_error], breaker=breaker)
    breaker.clock = h.clock
    with pytest.raises(ProviderUnavailableError):
        h.transcriber.transcribe(request(wav(1.0)))
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        h.transcriber.transcribe(request(wav(1.0)))
    assert len(h.transport.requests) == 2


def test_real_data_is_never_recorded() -> None:
    h = VoiceHarness([f.transcription("x")], transport_mode="record")
    with pytest.raises(RecordingForbiddenError):
        h.transcriber.transcribe(request(wav(1.0)))
    assert h.transport.requests == []


# --- record and replay ---------------------------------------------------------------------


def settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "model_api_key": SecretStr("test-key"),
        "llm_spend_ledger": str(tmp_path / "spend.jsonl"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_record_then_replay_keyed_by_the_audio_not_the_boundary(tmp_path: Path) -> None:
    cassettes = tmp_path / "cassettes"
    live = f.FakeTransport([f.transcription("Quel a été mon bénéfice ?", 3_000)])
    no_sleep = TranscribeRetryPolicy(sleep=lambda _: None)
    recorder = build_transcriber(
        settings(tmp_path),
        mode=LLMMode.RECORD,
        live_transport=live,
        cassette_dir=cassettes,
        retry=no_sleep,
    )
    audio = wav(3.0)
    synthetic = request(audio, data_origin=DataOrigin.SYNTHETIC, keywords=("Mug",))
    assert recorder.transcribe(synthetic).transcript == "Quel a été mon bénéfice ?"
    ((path, cassette),) = CassetteStore(cassettes).all()
    stored = path.read_text(encoding="utf-8")
    assert cassette.request["body"]["audio"]["sha256"] == hashlib.sha256(audio).hexdigest()
    assert "RIFF" not in stored  # the audio itself is not kept
    assert len(stored) < 4_000
    assert (tmp_path / "spend.jsonl").exists()  # recording spends real money

    replayer = build_transcriber(settings(tmp_path), mode=LLMMode.REPLAY, cassette_dir=cassettes)
    again = replayer.transcribe(synthetic.model_copy(update={"session_id": "other"}))
    assert (again.transcript, again.cost_usd) == ("Quel a été mon bénéfice ?", D("0.00015"))
    with pytest.raises(CassetteMissError, match=r"muse-voice-transcribe-1\.0"):
        replayer.transcribe(synthetic.model_copy(update={"audio": wav(3.0, tone=False)}))


def test_multipart_bodies_need_a_boundary() -> None:
    with pytest.raises(ValueError, match="boundary"):
        multipart_body(b"", "multipart/form-data")
    raw = (
        b'--b\r\nContent-Disposition: form-data; name="request"\r\n'
        b'Content-Type: application/json\r\n\r\n{"a": 1}\r\n--b--\r\n'
    )
    assert multipart_body(raw, 'multipart/form-data; boundary="b"') == {"request": {"a": 1}}


def test_closing_a_recorder_closes_the_real_connections(tmp_path: Path) -> None:
    closed: list[bool] = []

    class Live(f.FakeTransport):
        def close(self) -> None:
            closed.append(True)

    recorder = build_transcriber(
        settings(tmp_path), mode=LLMMode.RECORD, live_transport=Live([]), cassette_dir=tmp_path
    )
    recorder.close()
    assert closed == [True]
