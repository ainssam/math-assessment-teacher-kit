from __future__ import annotations

from app import visitor_counter


def test_counter_state_returns_incremented_exact_counter(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_counter_value(key: str, *, increment: bool) -> int:
        assert key == "total"
        calls.append(increment)
        return 27

    monkeypatch.setattr(visitor_counter, "_counter_value", fake_counter_value)

    value, incremented = visitor_counter._counter_state("total", increment=True)

    assert calls == [True]
    assert value == 27
    assert incremented is True


def test_counter_state_reads_without_increment(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_counter_value(key: str, *, increment: bool) -> int:
        assert key == "total"
        calls.append(increment)
        return 12

    monkeypatch.setattr(visitor_counter, "_counter_value", fake_counter_value)

    value, incremented = visitor_counter._counter_state("total", increment=False)

    assert calls == [False]
    assert value == 12
    assert incremented is False


def test_without_namespace_never_contacts_counter_service(monkeypatch) -> None:
    monkeypatch.delenv("MATH_ASSESSMENT_COUNTER_NAMESPACE", raising=False)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("external visitor counter request")

    monkeypatch.setattr(visitor_counter, "_counter_value", unexpected_request)
    result = visitor_counter.visitor_counts(increment_today=True, increment_total=True)

    assert result["today"] is None
    assert result["total"] is None
    assert result["available"] is False
