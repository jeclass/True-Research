"""Keys API — set/not-set status over .env + os.environ, conservative .env
writing. Hermetic: every test uses a tmp_path .env; os.environ via monkeypatch."""

import pytest
from pydantic import ValidationError

from src.webui import keys_api


def test_key_status_reports_all_allowlisted_keys(tmp_path, monkeypatch):
    for name in keys_api.KEY_ALLOWLIST:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-deep-123\n", encoding="utf-8")
    status = keys_api.key_status(env)
    by_name = {row["name"]: row for row in status}
    assert set(by_name) == set(keys_api.KEY_ALLOWLIST)
    assert by_name["DEEPSEEK_API_KEY"]["set"] is True
    assert by_name["ANTHROPIC_API_KEY"]["set"] is False
    for row in status:
        assert set(row) == {"name", "set", "used_for"}  # never a value field


def test_key_status_falls_back_to_os_environ(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    assert keys_api.is_key_set("ANTHROPIC_API_KEY", tmp_path / "no-such.env") is True


def test_set_key_creates_env_file(tmp_path):
    env = tmp_path / ".env"
    req = keys_api.SetKeyRequest(name="ANTHROPIC_API_KEY", value="sk-ant-abc")
    out = keys_api.set_key(req, env)
    assert out == {"name": "ANTHROPIC_API_KEY", "set": True}
    assert env.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-ant-abc\n"


def test_set_key_updates_in_place_preserving_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# my comment\nDEEPSEEK_API_KEY=old-value\nOTHER_THING=keep\n",
        encoding="utf-8",
    )
    keys_api.set_key(keys_api.SetKeyRequest(name="DEEPSEEK_API_KEY", value="new-value"), env)
    assert env.read_text(encoding="utf-8") == (
        "# my comment\nDEEPSEEK_API_KEY=new-value\nOTHER_THING=keep\n"
    )


def test_set_key_appends_when_absent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER_THING=keep\n", encoding="utf-8")
    keys_api.set_key(keys_api.SetKeyRequest(name="SERPER_API_KEY", value="ser-1"), env)
    assert env.read_text(encoding="utf-8") == "OTHER_THING=keep\nSERPER_API_KEY=ser-1\n"


def test_set_key_rejects_non_allowlisted_name():
    with pytest.raises(ValidationError):
        keys_api.SetKeyRequest(name="PATH", value="evil")


def test_set_key_rejects_empty_and_control_char_values():
    for bad in ["", "   ", "line1\nline2", "tab\tchar", "cr\rhere"]:
        with pytest.raises(ValidationError):
            keys_api.SetKeyRequest(name="ANTHROPIC_API_KEY", value=bad)


def test_set_key_value_is_stripped(tmp_path):
    env = tmp_path / ".env"
    keys_api.set_key(keys_api.SetKeyRequest(name="ANTHROPIC_API_KEY", value="  sk-x  "), env)
    assert "ANTHROPIC_API_KEY=sk-x\n" == env.read_text(encoding="utf-8")


# ---------- routes ----------

def _client(tmp_path, env_lines=""):
    from starlette.testclient import TestClient
    from src.webui.app import create_app
    env = tmp_path / ".env"
    if env_lines:
        env.write_text(env_lines, encoding="utf-8")
    return TestClient(create_app(runs_dir=tmp_path / "runs", env_path=env)), env


def test_api_keys_get_status_only(tmp_path, monkeypatch):
    for name in keys_api.KEY_ALLOWLIST:
        monkeypatch.delenv(name, raising=False)
    c, _ = _client(tmp_path, "ANTHROPIC_API_KEY=sk-ant-secret-value\n")
    r = c.get("/api/keys")
    assert r.status_code == 200
    by_name = {row["name"]: row for row in r.json()}
    assert by_name["ANTHROPIC_API_KEY"]["set"] is True
    assert by_name["DEEPSEEK_API_KEY"]["set"] is False
    assert "sk-ant-secret-value" not in r.text  # value never leaves the server


def test_api_keys_post_roundtrip_never_echoes_value(tmp_path, monkeypatch):
    for name in keys_api.KEY_ALLOWLIST:
        monkeypatch.delenv(name, raising=False)
    c, env = _client(tmp_path)
    r = c.post("/api/keys", json={"name": "DEEPSEEK_API_KEY", "value": "sk-deep-xyz"})
    assert r.status_code == 200
    assert r.json() == {"name": "DEEPSEEK_API_KEY", "set": True}
    assert "sk-deep-xyz" not in r.text
    assert "DEEPSEEK_API_KEY=sk-deep-xyz" in env.read_text(encoding="utf-8")
    assert "sk-deep-xyz" not in c.get("/api/keys").text


def test_api_keys_post_rejects_bad_name_and_value(tmp_path):
    c, _ = _client(tmp_path)
    assert c.post("/api/keys", json={"name": "PATH", "value": "x"}).status_code == 422
    assert c.post("/api/keys",
                  json={"name": "ANTHROPIC_API_KEY", "value": "a\nb"}).status_code == 422
    # 422 error body must not echo the submitted value
    r = c.post("/api/keys", json={"name": "ANTHROPIC_API_KEY", "value": "sk-oops\nx"})
    assert "sk-oops" not in r.text
