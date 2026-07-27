"""Régressions du domaine déterministe de conversion d'unités."""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import unit_conversion


async def convert(value: float, source: str, target: str) -> dict:
    return await unit_conversion.unit_convert({
        "value": value,
        "from_unit": source,
        "to_unit": target,
    })


async def run_domain() -> None:
    cases = (
        (1, "km", "m", 1000.0),
        (1, "mile", "km", 1.609344),
        (1, "lb", "kg", 0.45359237),
        (1, "gallon", "l", 3.785411784),
        (1, "knot", "m/s", 0.514444444),
        (1, "ha", "m2", 10000.0),
        (1, "ev", "j", 1.602176634e-19),
        (1, "gib", "mib", 1024.0),
    )
    for value, source, target, expected in cases:
        result = await convert(value, source, target)
        assert result["success"] is True, result
        assert math.isclose(result["result"], expected, rel_tol=1e-9, abs_tol=1e-25), result

    freezing = await convert(32, "°F", "celsius")
    assert freezing["result"] == 0.0
    absolute_zero = await convert(-273.15, "c", "k")
    assert absolute_zero["result"] == 0.0
    impossible = await convert(-1, "kelvin", "c")
    assert "zéro absolu" in impossible["error"]

    incompatible = await convert(1, "kg", "m")
    assert "incompatibles" in incompatible["error"]
    mixed_temperature = await convert(1, "c", "m")
    assert "incompatibles" in mixed_temperature["error"]
    unknown = await convert(1, "parsec", "m")
    assert "source inconnue" in unknown["error"]
    non_finite = await convert(float("inf"), "m", "km")
    assert "finie" in non_finite["error"]
    oversized = await convert(1e101, "m", "km")
    assert "1e100" in oversized["error"]


def main() -> int:
    asyncio.run(run_domain())

    import tools

    assert tools.execute_unit_convert is unit_conversion.unit_convert
    assert tools.TOOLS_REGISTRY["unit_convert"] is unit_conversion.unit_convert
    schema = next(
        item["function"]["parameters"]
        for item in tools.TOOLS_SPEC
        if item["function"]["name"] == "unit_convert"
    )
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["value", "from_unit", "to_unit"]
    print("Unit Conversion OK - SI, non-SI, temperature, limites, facade et schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
