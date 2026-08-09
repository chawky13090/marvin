"""Contrat pur des quatre profils et de leurs états de continuité."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from privacy_resilience import policy_for, runtime_state


def main() -> int:
    normal = policy_for("normal")
    assert normal.preferred_provider == "adaptive"
    assert normal.cloud_allowed and not normal.sensitive_cloud_allowed

    hyper = policy_for("hyper")
    assert hyper.local_required and not hyper.cloud_allowed

    cloud = policy_for("cloud_max")
    assert cloud.cloud_preferred and not cloud.sensitive_cloud_allowed

    ultra = policy_for("ultra")
    assert ultra.cloud_preferred and ultra.sensitive_cloud_allowed
    assert ultra.announced_local_continuity
    assert ultra.permissions_independent and not ultra.automatic_profile_change

    nominal = runtime_state("ultra", "ollama_cloud")
    assert nominal["cloudOnly"] is True and nominal["degraded"] is False
    degraded = runtime_state(
        "ultra",
        "ollama_local",
        fallback_reason="cloud_connectivity_unavailable",
    )
    assert degraded == {
        "privacyPreset": "ultra",
        "provider": "ollama_local",
        "cloudPreferred": True,
        "cloudOnly": False,
        "degraded": True,
        "continuityState": "local_continuity",
        "switchReason": "cloud_connectivity_unavailable",
    }
    assert policy_for("corrupted") == normal
    print("Privacy resilience OK - 4 profils, continuité annoncée et droits indépendants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
