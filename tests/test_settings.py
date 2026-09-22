from __future__ import annotations

from pathlib import Path

from instabotai.settings import Settings, get_settings, runtime_config_file, runtime_data_dir


def _clear_runtime_path_overrides(monkeypatch) -> None:
    for name in (
        "INSTABOTAI_STATE_DB_PATH",
        "INSTABOTAI_PRIVATE_SESSION_PATH",
        "INSTABOTAI_CONFIG_FILE",
        "INSTABOTAI_AI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_runtime_paths_are_stable_across_working_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_runtime_path_overrides(monkeypatch)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))

    first_cwd = tmp_path / "first"
    second_cwd = tmp_path / "second"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.chdir(first_cwd)
    first = Settings(_env_file=None)

    monkeypatch.chdir(second_cwd)
    second = Settings(_env_file=None)

    expected_root = tmp_path / "xdg-data" / "instabotai"
    assert runtime_data_dir() == expected_root
    assert first.state_db_path == str(expected_root / "instabotai.sqlite3")
    assert second.state_db_path == first.state_db_path
    assert first.private_session_path == str(expected_root / "private-instagram-session.json")
    assert second.private_session_path == first.private_session_path
    assert Path(first.state_db_path).is_absolute()
    assert Path(first.private_session_path).is_absolute()


def test_get_settings_uses_stable_per_user_config_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_runtime_path_overrides(monkeypatch)
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    config_file = config_home / "instabotai" / ".env"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("INSTABOTAI_AI_MODEL=canonical-config-model\n", encoding="utf-8")

    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    (unrelated_cwd / ".env").write_text(
        "INSTABOTAI_AI_MODEL=wrong-cwd-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(unrelated_cwd)

    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert runtime_config_file() == config_file
    assert settings.ai_model == "canonical-config-model"


def test_explicit_config_file_override_can_be_relative(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_runtime_path_overrides(monkeypatch)
    monkeypatch.chdir(tmp_path)
    operator_file = tmp_path / "operator.env"
    operator_file.write_text("INSTABOTAI_AI_MODEL=operator-model\n", encoding="utf-8")
    monkeypatch.setenv("INSTABOTAI_CONFIG_FILE", "operator.env")

    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert runtime_config_file() == operator_file
    assert settings.ai_model == "operator-model"


def test_explicit_state_and_session_paths_remain_authoritative(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_runtime_path_overrides(monkeypatch)
    state_path = tmp_path / "operator-state.sqlite3"
    session_path = tmp_path / "operator-session.json"
    monkeypatch.setenv("INSTABOTAI_STATE_DB_PATH", str(state_path))
    monkeypatch.setenv("INSTABOTAI_PRIVATE_SESSION_PATH", str(session_path))

    settings = Settings(_env_file=None)

    assert settings.state_db_path == str(state_path)
    assert settings.private_session_path == str(session_path)
