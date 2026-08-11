from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import runtime_config as runtime_api
from api import coding as coding_api
from api import vm_lab as vm_lab_api


def main() -> int:
    async def exercise() -> None:
        fake_learning = SimpleNamespace(
            count_learned=lambda: {"facts": 1, "qa": 1},
            list_learned=lambda kind, limit: [{"kind": kind, "limit": limit}],
        )
        with patch.dict(sys.modules, {"learning": fake_learning}):
            snapshot = await runtime_api.learning_list()
        assert snapshot["counts"] == {"facts": 1, "qa": 1}
        assert snapshot["facts"][0]["limit"] == 200
        assert snapshot["qa"][0]["limit"] == 100

        with patch.object(asyncio, "to_thread", new=AsyncMock(return_value={"source": "thread"})) as to_thread:
            assert await vm_lab_api.vm_lab_status() == {"source": "thread"}
            to_thread.assert_awaited_once_with(vm_lab_api.vm_lab.status)
        with patch.object(asyncio, "to_thread", new=AsyncMock(return_value={"job": "thread"})) as to_thread:
            assert await vm_lab_api.vm_lab_install_status() == {"job": "thread"}
            to_thread.assert_awaited_once_with(vm_lab_api.vm_lab_jobs.status)
        with patch.object(asyncio, "to_thread", new=AsyncMock(return_value={"coding": "thread"})) as to_thread:
            assert await coding_api.coding_overview() == {"coding": "thread"}
            to_thread.assert_awaited_once_with(coding_api._coding_overview_payload)

    asyncio.run(exercise())
    print("Nonblocking Read Routes OK - learning, Code Workspace and Hyper-V inventory leave the FastAPI event loop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
