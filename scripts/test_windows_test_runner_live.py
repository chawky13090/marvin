"""Real Windows Sandbox smoke test for Test Forge PowerShell execution."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import windows_test_runner


SCRIPT = r"""Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-MarvinSlug {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidateNotNullOrEmpty()]
        [string]$Text
    )

    $slug = $Text.Trim().ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    return $slug.Trim('-')
}
"""


TESTS = r"""BeforeAll {
    . 'C:\Marvin\Input\main.ps1'
}

Describe 'ConvertTo-MarvinSlug' {
    It 'normalise a production-style identifier' {
        ConvertTo-MarvinSlug -Text '  Marvin Test Forge 2026  ' |
            Should -BeExactly 'marvin-test-forge-2026'
    }

    It 'removes leading and trailing separators' {
        ConvertTo-MarvinSlug -Text '---Alpha---' | Should -BeExactly 'alpha'
    }

    It 'rejects an empty value' {
        { ConvertTo-MarvinSlug -Text '' } | Should -Throw
    }
}
"""


def main() -> int:
    status = windows_test_runner.status()
    if not status["available"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2

    result = windows_test_runner.execute_powershell(
        SCRIPT,
        TESTS,
        timeout_seconds=900,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    required_steps = {
        "windows_network_guard",
        "powershell_parser_vm",
        "windows_dependencies",
        "psscriptanalyzer_vm",
        "pester_vm",
    }
    passed_steps = {
        str(step.get("name"))
        for step in result.get("steps", [])
        if step.get("passed") is True
    }
    if not result.get("production_ready"):
        return 1
    if result.get("tests_executed") is not True:
        return 1
    if not required_steps.issubset(passed_steps):
        return 1
    print("Windows Test Forge Live OK - Sandbox, PSGallery, PSScriptAnalyzer et Pester verifies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
