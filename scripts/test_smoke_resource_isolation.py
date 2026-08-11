from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    voice = (ROOT / "scripts" / "smoke_test_voice.py").read_text(encoding="utf-8")
    chat = (ROOT / "scripts" / "smoke_test_chat.py").read_text(encoding="utf-8")
    assert "uuid.uuid4().hex" in voice
    assert "cleanup_orphan_voice_fixtures" not in voice
    assert "search_conversations(VOICE_FIXTURE_PREFIX" not in voice
    assert "atexit.register(db.delete_conversation, fixture_id)" in voice
    assert 'title.startswith("[SMOKE:")' in chat
    assert "with browser_smoke_lock():" in voice
    assert "with browser_smoke_lock():" in chat
    lock = (ROOT / "scripts" / "smoke_run_lock.py").read_text(encoding="utf-8")
    assert "LK_NBLCK" in lock and "LOCK_EX | fcntl.LOCK_NB" in lock
    assert "browser_smoke_lock_timeout" in lock
    print("Smoke Resource Isolation OK - fixture unique, nettoyage local et execution serialisee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
