import pytest

from spendfuse.engine import Rule, Sample, SpendEngine, clamp_max_history, clamp_poll_interval


def test_rule_requires_absolute_or_rate_condition():
    with pytest.raises(ValueError):
        Rule(name="bad", actions=["a"])


def test_rule_requires_actions():
    with pytest.raises(ValueError):
        Rule(name="bad", actions=[], max_total_usd=10)


def test_absolute_threshold_triggers_once_then_rearms():
    rule = Rule(name="ceiling", actions=["a"], max_total_usd=100.0)
    engine = SpendEngine([rule])

    engine.add_sample(Sample(timestamp=0, total_usd=50))
    assert engine.evaluate() == []

    engine.add_sample(Sample(timestamp=10, total_usd=150))
    triggers = engine.evaluate()
    assert len(triggers) == 1
    assert triggers[0].rule.name == "ceiling"
    assert "absolute ceiling exceeded" in triggers[0].reason

    # still breached -- must not re-fire every poll
    engine.add_sample(Sample(timestamp=20, total_usd=160))
    assert engine.evaluate() == []

    # drop back under, then cross again -- should re-arm and fire again
    engine.add_sample(Sample(timestamp=30, total_usd=10))
    assert engine.evaluate() == []
    engine.add_sample(Sample(timestamp=40, total_usd=200))
    triggers = engine.evaluate()
    assert len(triggers) == 1


def test_rate_threshold_uses_linear_regression_slope():
    # perfectly linear: $2/sec = $120/min
    rule = Rule(name="rate", actions=["a"], max_rate_usd_per_minute=100.0, window_minutes=5)
    engine = SpendEngine([rule])

    for i in range(5):
        engine.add_sample(Sample(timestamp=i * 10, total_usd=i * 20))  # $2/sec

    rate = engine.compute_rate_usd_per_minute(window_minutes=5, now=40)
    assert rate == pytest.approx(120.0, rel=1e-6)

    triggers = engine.evaluate()
    assert len(triggers) == 1
    assert "spend accelerating" in triggers[0].reason


def test_rate_threshold_not_triggered_when_slow():
    rule = Rule(name="rate", actions=["a"], max_rate_usd_per_minute=100.0, window_minutes=5)
    engine = SpendEngine([rule])

    for i in range(5):
        engine.add_sample(Sample(timestamp=i * 10, total_usd=i * 1))  # $0.1/sec = $6/min

    assert engine.evaluate() == []


def test_rate_ignores_samples_outside_window():
    rule = Rule(name="rate", actions=["a"], max_rate_usd_per_minute=10.0, window_minutes=1)
    engine = SpendEngine([rule])

    # an old, huge jump well outside the 1-minute window...
    engine.add_sample(Sample(timestamp=0, total_usd=0))
    engine.add_sample(Sample(timestamp=1, total_usd=1000))
    # ...followed by a slow, recent trickle inside the window
    engine.add_sample(Sample(timestamp=120, total_usd=1001))
    engine.add_sample(Sample(timestamp=150, total_usd=1002))

    rate = engine.compute_rate_usd_per_minute(window_minutes=1, now=150)
    # only the last two points (30s apart, $1 apart) should count: $2/min
    assert rate == pytest.approx(2.0, rel=1e-6)


def test_history_is_bounded():
    rule = Rule(name="ceiling", actions=["a"], max_total_usd=1_000_000)
    engine = SpendEngine([rule], max_history=10)
    for i in range(20):
        engine.add_sample(Sample(timestamp=i, total_usd=i))
    assert len(engine.history) == 10
    assert engine.history[0].timestamp == 10  # oldest 10 dropped


def test_clamp_helpers():
    assert clamp_poll_interval(0) == 1
    assert clamp_poll_interval(999999) == 3600
    assert clamp_poll_interval(30) == 30
    assert clamp_max_history(1) == 10
    assert clamp_max_history(10 ** 9) == 100_000


def test_duplicate_rule_names_rejected():
    r1 = Rule(name="dup", actions=["a"], max_total_usd=1)
    r2 = Rule(name="dup", actions=["a"], max_total_usd=2)
    with pytest.raises(ValueError):
        SpendEngine([r1, r2])
