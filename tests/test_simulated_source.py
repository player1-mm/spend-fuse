from spendfuse.sources.simulated import SimulatedCostSource


def test_starts_at_initial_value(tmp_path):
    source = SimulatedCostSource(tmp_path / "state.json", initial_usd=42.0, increment_usd=0.0)
    reading = source.get_current_spend()
    assert reading.total_usd == 42.0


def test_increments_each_call(tmp_path):
    source = SimulatedCostSource(tmp_path / "state.json", initial_usd=0.0, increment_usd=5.0)
    r1 = source.get_current_spend()
    r2 = source.get_current_spend()
    r3 = source.get_current_spend()
    assert [r1.total_usd, r2.total_usd, r3.total_usd] == [5.0, 10.0, 15.0]


def test_state_persists_across_new_instances(tmp_path):
    state_file = tmp_path / "state.json"
    source1 = SimulatedCostSource(state_file, initial_usd=0.0, increment_usd=10.0)
    source1.get_current_spend()
    source1.get_current_spend()

    # simulate a process restart: a fresh instance reads the persisted total
    source2 = SimulatedCostSource(state_file, initial_usd=0.0, increment_usd=10.0)
    reading = source2.get_current_spend()
    assert reading.total_usd == 30.0


def test_reset(tmp_path):
    source = SimulatedCostSource(tmp_path / "state.json", initial_usd=0.0, increment_usd=1.0)
    source.get_current_spend()
    source.get_current_spend()
    source.reset(0.0)
    reading = source.get_current_spend()
    assert reading.total_usd == 1.0


def test_timestamps_are_monotonic_nondecreasing(tmp_path):
    source = SimulatedCostSource(tmp_path / "state.json")
    r1 = source.get_current_spend()
    r2 = source.get_current_spend()
    assert r2.timestamp >= r1.timestamp
