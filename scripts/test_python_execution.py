"""Régressions de l'exécuteur Python borné, sans toucher aux données Marvin."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import python_execution
import tools


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-python-") as temporary:
        root = Path(temporary)
        counter = iter(f"run-{index}" for index in range(20))
        python_execution.configure(
            output_root=root,
            python_executable=sys.executable,
            id_factory=lambda: next(counter),
        )
        result = await python_execution.execute(
            {"code": "result = sum(i * i for i in range(5))"}
        )
        assert result["success"] is True
        assert result["result"] == "30"
        assert result["isolation"] == "process_only"
        assert result["sandboxed"] is False
        assert result["environment_inherited"] is False

        numpy_result = await python_execution.execute(
            {"code": "import numpy as np\nresult = int(np.array([2, 3]).sum())"}
        )
        assert numpy_result["success"] is True
        assert numpy_result["result"] == "5"

        for code in (
            "import os\nprint(os.getcwd())",
            "from pathlib import Path\nprint(Path.cwd())",
            "import numpy as np\nnp.save('x.npy', [1])",
            "().__class__.__base__.__subclasses__()",
        ):
            blocked = await python_execution.execute({"code": code})
            assert blocked["requiresConfirmation"] is True
            assert blocked["sandboxed"] is False

        secret_name = "MARVIN_EXECUTION_SECRET_TEST"
        os.environ[secret_name] = "must-not-leak"
        try:
            confirmed = await python_execution.execute(
                {
                    "code": (
                        "import os\n"
                        f"print(os.environ.get('{secret_name}', 'absent'))\n"
                        "open('artifact.txt', 'w', encoding='utf-8').write('proof')"
                    ),
                    "confirmed": True,
                }
            )
        finally:
            os.environ.pop(secret_name, None)
        assert confirmed["success"] is True
        assert confirmed["stdout"] == "absent"
        assert confirmed["environment_inherited"] is False
        assert confirmed["network_isolated"] is False
        assert confirmed["warning"]
        assert len(confirmed["artifacts"]) == 1
        assert Path(confirmed["path"]).read_text(encoding="utf-8") == "proof"

        noisy = await python_execution.execute(
            {"code": "print('x' * 100000)"}
        )
        assert noisy["success"] is True
        assert noisy["stdout_truncated"] is True
        assert len(noisy["stdout"].encode("utf-8")) <= 64_000

        timed_out = await python_execution.execute(
            {"code": "while True:\n    pass", "timeout": 1}
        )
        assert timed_out["timed_out"] is True
        assert timed_out["sandboxed"] is False

        syntax = await python_execution.execute({"code": "if:"})
        assert "syntaxe" in syntax["error"]
        assert "timeout" in (
            await python_execution.execute({"code": "result=1", "timeout": 0})
        )["error"]
        assert "100000" in (
            await python_execution.execute({"code": "x" * 100_001})
        )["error"]

    python_execution.configure(
        output_root=Path(tools.__file__).resolve().parent.parent
        / "data"
        / "code_outputs",
        python_executable=sys.executable,
    )
    assert tools.execute_code_python is python_execution.execute
    assert tools.TOOLS_REGISTRY["code_python"] is python_execution.execute


if __name__ == "__main__":
    asyncio.run(main())
    print("Python Execution OK - bornes, confirmation, environnement et timeout.")
