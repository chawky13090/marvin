"""Régression : panne réseau Cloud simulée et repli local de continuité (v2.524).

Avant cette tranche, aucun mécanisme ne distinguait "ce modèle Cloud a un problème
ponctuel" (repli déjà existant : essayer un AUTRE modèle Cloud) de "le Cloud entier
est injoignable" (aucun repli n'existait : la conversation s'arrêtait sur une erreur
brute après épuisement des tentatives cloud-à-cloud). Le repli "local" déjà présent
dans le code (`sensitive_tool_model_switch`) est un repli de CONFIDENTIALITÉ — il se
déclenche sur le contenu, jamais sur une panne — et ne doit pas être confondu avec
celui-ci.

Méthode : `httpx.MockTransport` simule une VRAIE panne de connexion au niveau du
transport HTTP (le mécanisme standard pour tester une panne réseau sans couper la
connexion réelle de la machine), exactement comme `test_agent_transport.py` le fait
déjà pour les autres erreurs de transport. Cela prouve que `agent_transport.stream_chat`
lève effectivement l'exception que `retryable_cloud_model_error` doit reconnaître.

Portée déclarée : ce test valide le transport et les fonctions de décision pures
(`agent_loop_policy.py`) en conditions réalistes. Il ne fait PAS tourner `run_agent`
dans son intégralité (base de données, SSE, conversation) — ce harnais lourd n'existe
pas encore dans le projet pour cette boucle ; le câblage exact dans `agent.py` reste
donc vérifié par lecture de code, pas par exécution de bout en bout. Limite déclarée,
pas masquée.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_loop_policy as policy
import agent_transport as transport


def _request() -> transport.OllamaChatRequest:
    return transport.OllamaChatRequest(
        model="deepseek-v4-pro:cloud",
        system_prompt="Règle système",
        messages=[{"role": "system", "content": "Règle système"}],
        tools=None,
        options={"temperature": 0.1, "top_p": 0.9},
    )


async def _simulate_total_outage() -> Exception:
    """Panne réseau totale : toute tentative de connexion échoue, comme un Wi-Fi coupé."""
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed (panne simulée)")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        try:
            async for _ in transport.stream_chat(client, "http://127.0.0.1:11434/", _request()):
                pass
        except Exception as exc:  # noqa: BLE001 - on veut l'exception réelle levée
            return exc
    raise AssertionError("la panne simulée aurait dû lever une exception")


async def _simulate_read_timeout() -> Exception:
    """Le Cloud accepte la connexion mais ne répond jamais (lien saturé/coupé en cours)."""
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("délai dépassé (panne simulée)")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        try:
            async for _ in transport.stream_chat(client, "http://127.0.0.1:11434/", _request()):
                pass
        except Exception as exc:  # noqa: BLE001
            return exc
    raise AssertionError("le timeout simulé aurait dû lever une exception")


async def _check_transport_classifies_real_outage() -> None:
    outage = await _simulate_total_outage()
    assert isinstance(outage, httpx.ConnectError), type(outage)
    assert policy.retryable_cloud_model_error(outage) is True, (
        "une vraie panne de connexion doit être reconnue comme retryable"
    )

    timeout = await _simulate_read_timeout()
    assert isinstance(timeout, httpx.ReadTimeout), type(timeout)
    assert policy.retryable_cloud_model_error(timeout) is True


def _is_cloud(name: str) -> bool:
    return name.endswith(":cloud")


def _check_local_fallback_decision() -> None:
    base = dict(
        active_model="deepseek-v4-pro:cloud",
        profile_name="agent",
        local_fallback_model="qwen2.5:14b",
        ultra_cloud_only=False,
        is_cloud_model=_is_cloud,
        already_attempted=False,
    )

    # 1. Panne Cloud, mode normal : bascule vers le modèle local disponible.
    switch = policy.connectivity_local_fallback(**base)
    assert switch is not None
    assert switch.model == "qwen2.5:14b"
    assert switch.event["switchReason"] == "cloud_connectivity_unavailable"
    assert switch.event["provider"] == "ollama_local"

    # 2. Contrat Ultra cloud-only : JAMAIS de repli local, la panne reste visible.
    assert policy.connectivity_local_fallback(**{**base, "ultra_cloud_only": True}) is None

    # 3. Anti-boucle : déjà tenté une fois ce tour, pas de deuxième bascule.
    assert policy.connectivity_local_fallback(**{**base, "already_attempted": True}) is None

    # 4. Modèle déjà local : rien à faire.
    assert policy.connectivity_local_fallback(
        **{**base, "active_model": "qwen2.5:14b"}
    ) is None

    # 5. Aucun repli configuré : pas de crash, pas de bascule.
    assert policy.connectivity_local_fallback(**{**base, "local_fallback_model": ""}) is None

    # 6. Configuration incohérente (le "repli" est lui-même un modèle Cloud) : refusé.
    assert policy.connectivity_local_fallback(
        **{**base, "local_fallback_model": "glm-5.2:cloud"}
    ) is None


def _check_wired_after_cloud_retries_exhausted() -> None:
    """Le repli local doit rester atteignable même quand le cloud-à-cloud est épuisé.

    Contrôle textuel ciblé : la régression réelle rencontrée pendant le développement
    était que `_connectivity_local_fallback` était imbriqué sous la même condition que
    la boucle cloud-à-cloud (`len(_failed_cloud_models) < 2`), ce qui l'empêchait de se
    déclencher précisément après épuisement des alternatives — le cas où il est
    nécessaire. On vérifie que l'appel n'est plus sous cette garde.
    """
    source = (BACKEND / "agent.py").read_text(encoding="utf-8")
    assert "_connectivity_local_fallback(" in source
    before, _, _ = source.partition("_connectivity_local_fallback(")
    # Le bloc juste avant l'appel ne doit plus contenir la garde qui l'empêchait
    # de s'exécuter une fois les tentatives cloud épuisées.
    tail = before[before.rfind("except Exception as exc:"):]
    assert "if _cloud_retry_eligible:" in tail, (
        "le repli local doit être atteignable indépendamment du compteur "
        "d'alternatives cloud épuisées"
    )


def main() -> int:
    asyncio.run(_check_transport_classifies_real_outage())
    _check_local_fallback_decision()
    _check_wired_after_cloud_retries_exhausted()
    print(
        "Connectivity Resilience OK - panne reseau classifiee, repli local de "
        "continuite distinct de la confidentialite, contrat Ultra preserve."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
