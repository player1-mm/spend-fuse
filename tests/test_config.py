import pytest

from spendfuse.config import ConfigError, load_config, write_default_config


def test_write_default_config_and_load(tmp_path):
    config_path = tmp_path / ".spendfuse" / "config.yaml"
    write_default_config(config_path)
    assert config_path.exists()

    config = load_config(config_path)
    assert config.cost_source_type == "simulated"
    assert config.poll_interval_seconds == 5
    assert len(config.rules) == 1
    assert config.rules[0].name == "runaway_spend"
    assert "log_alert" in config.actions


def test_write_default_config_refuses_overwrite_without_force(tmp_path):
    config_path = tmp_path / "config.yaml"
    write_default_config(config_path)
    with pytest.raises(ConfigError):
        write_default_config(config_path)
    write_default_config(config_path, force=True)  # should not raise


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_poll_interval_is_clamped(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
cost_source:
  type: simulated
poll_interval_seconds: 999999
rules:
  - name: r1
    max_total_usd: 10
    actions: [a1]
actions:
  a1:
    type: shell
    command: "echo hi"
"""
    )
    config = load_config(config_path)
    assert config.poll_interval_seconds == 3600


def test_rule_referencing_undefined_action_rejected(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
cost_source:
  type: simulated
rules:
  - name: r1
    max_total_usd: 10
    actions: [missing_action]
actions:
  a1:
    type: shell
    command: "echo hi"
"""
    )
    with pytest.raises(ConfigError):
        load_config(config_path)


def test_rule_missing_conditions_rejected(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
cost_source:
  type: simulated
rules:
  - name: r1
    actions: [a1]
actions:
  a1:
    type: shell
    command: "echo hi"
"""
    )
    with pytest.raises(ConfigError):
        load_config(config_path)


def test_missing_cost_source_rejected(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
rules:
  - name: r1
    max_total_usd: 10
    actions: [a1]
actions:
  a1:
    type: shell
    command: "echo hi"
"""
    )
    with pytest.raises(ConfigError):
        load_config(config_path)
