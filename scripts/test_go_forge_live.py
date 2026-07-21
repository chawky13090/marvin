"""Live isolated Go 1.26.5 compilation, vet and test smoke for Test Forge."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import production_contract
import test_forge


def main() -> int:
    code = (
        "package main\n\n"
        "func Double(value int) int {\n\treturn value * 2\n}\n\n"
        "func main() {}\n"
    )
    tests = (
        "package main\n\nimport \"testing\"\n\n"
        "func TestDouble(t *testing.T) {\n"
        "\ttests := []struct {\n\t\tin   int\n\t\twant int\n\t}{\n"
        "\t\t{in: 0, want: 0},\n\t\t{in: 21, want: 42},\n\t\t{in: -2, want: -4},\n\t}\n"
        "\tfor _, tc := range tests {\n"
        "\t\tif got := Double(tc.in); got != tc.want {\n"
        "\t\t\tt.Fatalf(\"Double(%d)=%d want %d\", tc.in, got, tc.want)\n"
        "\t\t}\n\t}\n}\n"
    )
    files = {"go.mod": "module example.com/marvin/live\n\ngo 1.26\n"}
    report = test_forge.execute(code, "go", test_code=tests, files=files)
    if not report.get("production_ready"):
        raise AssertionError(f"Go Test Forge a échoué : {report}")
    contract = production_contract.evaluate({"main.go": code, **files}, "go", report)
    if not contract.get("success"):
        raise AssertionError(f"Production Contract Go a échoué : {contract}")
    names = {step["name"] for step in report["steps"] if step.get("passed")}
    if not {"gofmt", "go_vet", "go_test", "go_build_windows"}.issubset(names):
        raise AssertionError(f"Preuves Go incomplètes : {names}")
    print("Go Forge Live OK - Go 1.26.5, gofmt, go vet, go test et Production Contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
