"""Record / replay modes, the provider factory, the synthetic cassettes and the smoke check."""

import json
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from app.agent.llm import DataOrigin, ModelId
from app.agent.llm import fake as f
from app.agent.llm.cassette import (
    CassetteStore,
    LLMMode,
    RecordTransport,
    ReplayTransport,
    cassette_key,
)
from app.agent.llm.errors import CassetteMissError, MissingApiKeyError, RecordingForbiddenError
from app.agent.llm.factory import build_provider
from app.agent.llm.smoke import SmokeAnswer, run, run_model
from app.config import REPO_ROOT, Settings, repo_path
from scripts import smoke_live
from tests.cassettes import synthetic_build
from tests.llm_helpers import Harness, request

COMMITTED = repo_path("backend/tests/cassettes")


def settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "model_api_key": None,
        "llm_spend_ledger": str(tmp_path / "spend.jsonl"),
        "llm_cassette_dir": str(tmp_path / "cassettes"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_replay_is_the_default_mode_and_needs_no_key(tmp_path: Path) -> None:
    s = settings(tmp_path)
    assert s.llm_mode == "replay"
    provider = build_provider(s, cassette_dir=COMMITTED)
    assert provider.transport_mode == "replay"
    outcomes = run(provider, list(ModelId))
    assert [o.ok for o in outcomes] == [True, True, True], [o.detail for o in outcomes]
    assert not (tmp_path / "spend.jsonl").exists()  # replay spends nothing


def test_a_cassette_miss_fails_instead_of_calling_out(tmp_path: Path) -> None:
    provider = build_provider(settings(tmp_path))  # empty cassette directory
    with pytest.raises(CassetteMissError, match="LLM_MODE=record"):
        provider.generate(request())


def test_live_and_record_need_a_key(tmp_path: Path) -> None:
    for mode in (LLMMode.LIVE, LLMMode.RECORD):
        with pytest.raises(MissingApiKeyError):
            build_provider(settings(tmp_path), mode=mode)


def test_live_mode_sends_the_key_and_records_spend(tmp_path: Path) -> None:
    transport = f.FakeTransport([f.ok([f.message("hi")])])
    s = settings(tmp_path, model_api_key=SecretStr("LLM_1_secret"))
    provider = build_provider(s, mode=LLMMode.LIVE, live_transport=transport)
    result = provider.generate(request())
    assert transport.headers[0]["authorization"] == "Bearer LLM_1_secret"
    ledger = (tmp_path / "spend.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["kind"] for line in ledger] == ["reserve", "settle"]
    assert provider.budget.spent("default").total == result.cost_usd


def test_record_writes_cassettes_that_replay_identically(tmp_path: Path) -> None:
    upstream = f.FakeTransport(
        [
            f.Reply(
                200,
                f.response([f.message("recorded")]),
                {"x-ratelimit-remaining-requests": "2999", "set-cookie": "secret=1"},
            ),
            f.rate_limited(retry_after=0.5),
        ]
    )
    s = settings(tmp_path, model_api_key=SecretStr("LLM_1_secret"))
    recorder = build_provider(s, mode=LLMMode.RECORD, live_transport=upstream)
    synthetic = request(data_origin=DataOrigin.SYNTHETIC)
    assert recorder.generate(synthetic).text == "recorded"
    store = CassetteStore(tmp_path / "cassettes")
    ((path, cassette),) = store.all()
    assert path.parent.name == "recorded"
    assert cassette.synthetic is False
    assert cassette.headers == {
        "content-type": "application/json",
        "x-ratelimit-remaining-requests": "2999",
    }
    text = path.read_text(encoding="utf-8")
    assert "LLM_1_secret" not in text  # headers of the request, the key included, are not kept
    assert "secret=1" not in text
    replayed = build_provider(s, mode=LLMMode.REPLAY)
    assert replayed.generate(synthetic).text == "recorded"
    with pytest.raises(RecordingForbiddenError):
        recorder.generate(request(data_origin=DataOrigin.REAL))
    assert upstream.remaining == 1  # the refused call never left the process


def test_recorded_cassettes_win_over_synthetic_ones(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    inner = f.FakeTransport([f.ok([f.message("synthetic")]), f.ok([f.message("real")])])
    body = {"model": "muse-spark-1.3", "input": "x"}

    def post(transport: httpx2.BaseTransport) -> httpx2.Response:
        client = httpx2.Client(transport=transport, base_url="https://api.meta.ai/v1")
        return client.post("/responses", json=body)

    post(RecordTransport(inner, store, synthetic=True, note="hand-written"))
    post(RecordTransport(inner, store))
    answer = post(ReplayTransport(store)).json()
    assert answer["output"][0]["content"][0]["text"] == "real"
    # A cassette file must hold the cassette its name says.
    key = cassette_key({"method": "POST", "path": "/v1/responses", "body": body})
    (store.recorded / f"{key}.json").rename(store.recorded / f"{'0' * 64}.json")
    with pytest.raises(ValueError, match="holds cassette"):
        store.find("0" * 64)


def test_committed_cassettes_are_marked_and_current(tmp_path: Path) -> None:
    store = CassetteStore(COMMITTED)
    committed = store.all()
    assert committed, "synthetic cassettes are missing"
    for path, cassette in committed:
        assert cassette.key == path.stem
        if path.parent.name == "synthetic":
            assert cassette.synthetic
            assert "pending live verification" in cassette.note
        else:
            assert not cassette.synthetic
    # Rebuilding gives the same files: cassette keys still match what the provider sends.
    rebuilt = synthetic_build.build(tmp_path)
    committed_synthetic = {p.name for p, _ in committed if p.parent.name == "synthetic"}
    assert committed_synthetic == {p.name for p in rebuilt}, "unreachable synthetic cassettes"
    for path in rebuilt:
        twin = COMMITTED / "synthetic" / path.name
        assert twin.exists(), f"stale synthetic cassettes: run {synthetic_build.__file__}"
        assert json.loads(path.read_text(encoding="utf-8")) == json.loads(
            twin.read_text(encoding="utf-8")
        )


def test_smoke_reports_every_kind_of_difference() -> None:
    answer = {"fact_reference": "{{F1}}", "used_tool": True}
    call = f.function_call("get_fact", {"fact_id": 1}, call_id="c1")
    cases = {
        "response model": [f.ok([call], model="muse-spark-1.2")],
        "expected a get_fact call": [f.structured(answer)],
        "unknown tool": [f.ok([f.function_call("delete_store", {})])],
        "invalid get_fact arguments": [f.ok([f.function_call("get_fact", {"id": "x"})])],
        "another tool call": [f.ok([call]), f.ok([call])],
        "no structured answer": [f.ok([call]), f.ok([f.refusal("no")])],
        "does not echo": [f.ok([call]), f.structured({**answer, "fact_reference": "F1"})],
        "ResponseFormatError": [f.Reply(200, {"object": "response"})],
    }
    for expected, steps in cases.items():
        h = Harness(steps)
        outcome = run_model(h.provider, ModelId.SPARK)
        assert not outcome.ok
        assert expected in outcome.detail, (expected, outcome.detail)
    good = Harness([f.ok([call]), f.structured(answer)])
    outcome = run_model(good.provider, ModelId.SPARK)
    assert outcome.ok
    assert outcome.cost_usd == Decimal("0.00042")
    assert SmokeAnswer(**answer).used_tool


def test_smoke_script(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LLM_CASSETTE_DIR", str(COMMITTED))
    monkeypatch.setenv("LLM_SPEND_LEDGER", str(tmp_path / "spend.jsonl"))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert smoke_live.main(["--mode", "replay"]) == 0
        out = capsys.readouterr().out
        assert "muse-wonder-1.0" in out
        assert "no money spent" in out
        monkeypatch.setenv("LLM_CASSETTE_DIR", str(tmp_path / "empty"))
        get_settings.cache_clear()
        assert smoke_live.main(["--mode", "replay", "--model", "muse-spark-1.3"]) == 1
        assert "SMOKE FAILED for muse-spark-1.3" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()


def test_repo_paths() -> None:
    assert repo_path("backend") == REPO_ROOT / "backend"
    assert repo_path(str(REPO_ROOT)) == REPO_ROOT
