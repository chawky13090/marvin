"""Contrat déterministe de résilience des quatre profils de confidentialité.

Le profil choisi par l'utilisateur ne change jamais automatiquement. Ce module
décrit séparément la destination nominale, les destinations autorisées et l'état
de continuité effectif afin qu'un repli ne soit jamais silencieux.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


PrivacyPreset = Literal["normal", "hyper", "cloud_max", "ultra"]


@dataclass(frozen=True, slots=True)
class PrivacyResiliencePolicy:
    preset: PrivacyPreset
    label: str
    preferred_provider: Literal["adaptive", "ollama_local", "ollama_cloud"]
    cloud_allowed: bool
    sensitive_cloud_allowed: bool
    local_required: bool
    announced_local_continuity: bool
    automatic_profile_change: bool = False
    permissions_independent: bool = True

    @property
    def cloud_preferred(self) -> bool:
        return self.preferred_provider == "ollama_cloud"

    def public_contract(self) -> dict[str, object]:
        return {**asdict(self), "cloud_preferred": self.cloud_preferred}


_POLICIES: dict[PrivacyPreset, PrivacyResiliencePolicy] = {
    "normal": PrivacyResiliencePolicy(
        preset="normal",
        label="Normal adaptatif",
        preferred_provider="adaptive",
        cloud_allowed=True,
        sensitive_cloud_allowed=False,
        local_required=False,
        announced_local_continuity=True,
    ),
    "hyper": PrivacyResiliencePolicy(
        preset="hyper",
        label="Hyper sécurisé local",
        preferred_provider="ollama_local",
        cloud_allowed=False,
        sensitive_cloud_allowed=False,
        local_required=True,
        announced_local_continuity=True,
    ),
    "cloud_max": PrivacyResiliencePolicy(
        preset="cloud_max",
        label="Cloud prioritaire protégé",
        preferred_provider="ollama_cloud",
        cloud_allowed=True,
        sensitive_cloud_allowed=False,
        local_required=False,
        announced_local_continuity=True,
    ),
    "ultra": PrivacyResiliencePolicy(
        preset="ultra",
        label="Ultra débridé cloud prioritaire",
        preferred_provider="ollama_cloud",
        cloud_allowed=True,
        sensitive_cloud_allowed=True,
        local_required=False,
        announced_local_continuity=True,
    ),
}


def policy_for(preset: str) -> PrivacyResiliencePolicy:
    """Retourne le contrat exact; un profil inconnu échoue fermé sur Normal."""
    return _POLICIES.get(str(preset), _POLICIES["normal"])


def runtime_state(
    preset: str,
    provider: str,
    *,
    fallback_reason: str | None = None,
) -> dict[str, object]:
    """Construit un état public sans confondre profil, fournisseur et panne."""
    policy = policy_for(preset)
    local_continuity = (
        provider == "ollama_local"
        and policy.cloud_preferred
        and bool(fallback_reason)
    )
    return {
        "privacyPreset": policy.preset,
        "provider": provider,
        "cloudPreferred": policy.cloud_preferred,
        "cloudOnly": policy.cloud_preferred and provider == "ollama_cloud",
        "degraded": local_continuity,
        "continuityState": "local_continuity" if local_continuity else "nominal",
        "switchReason": fallback_reason,
    }
