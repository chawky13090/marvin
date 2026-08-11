from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = Path(tempfile.gettempdir()) / (
    "marvin-browser-smoke-" + hashlib.sha256(str(ROOT).casefold().encode("utf-8")).hexdigest()[:16] + ".lock"
)


@contextlib.contextmanager
def browser_smoke_lock(timeout_seconds: float = 180.0) -> Iterator[None]:
    """Serialize browser smokes that share the live Marvin runtime."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    stream = LOCK_PATH.open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        while not acquired:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("browser_smoke_lock_timeout")
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
