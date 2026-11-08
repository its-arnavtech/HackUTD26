"""L13 setup scripts: keys are written, never printed, and rotation keeps old data readable."""

from __future__ import annotations

from scripts import auth_keys

from app.crypto import KeyRing


def _env(path):
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)


def test_auth_keys_creates_then_rotates_without_printing(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("API_PORT=8000\n", encoding="utf-8")
    auth_keys.main([], env_path=env)
    first = _env(env)
    assert first["API_PORT"] == "8000" and first["JWT_PRIVATE_KEY"] and first["DATA_ENCRYPTION_KEYS"].startswith("k1:")
    token = KeyRing.parse(first["DATA_ENCRYPTION_KEYS"]).encrypt("secret", b"ctx")

    auth_keys.main([], env_path=env)  # idempotent
    assert _env(env) == first

    auth_keys.main(["--rotate"], env_path=env)
    rotated = _env(env)
    assert rotated["JWT_PRIVATE_KEY"] != first["JWT_PRIVATE_KEY"] and rotated["JWT_KEY_ID"] == "k2"
    ring = KeyRing.parse(rotated["DATA_ENCRYPTION_KEYS"])
    assert ring.current_id == "k2" and ring.decrypt_text(token, b"ctx") == "secret"

    out = capsys.readouterr().out
    for value in (first["JWT_PRIVATE_KEY"], rotated["JWT_PRIVATE_KEY"], first["DATA_ENCRYPTION_KEYS"].split(":", 1)[1]):
        assert value not in out
