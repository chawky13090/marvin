"""Regressions deterministes des garde-fous de consolidation automatique (v2.517).

Contexte mesure avant correction : le worker de consolidation ecrivait dans le Learning
Log qu il relit ensuite, sans cooldown, sans controle d existence et sans validation des
outils. Resultat constate en conditions reelles : 17 competences quasi identiques en 38 h
sur le theme « empecher les consolidations repetees », et 18,3 % des references d outils
de la bibliotheque pointant vers des noms inexistants.

Ces tests s executent dans un dossier de competences temporaire : ils n ecrivent jamais
dans data/skills.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import skills


REAL_TOOLS = ["file_find", "web_search", "memory_list", "pc_get_real_paths"]


def _isolate(tmp: Path) -> None:
    """Redirige tout l etat persistant de skills vers un dossier jetable."""
    skills._SKILLS_DIR = str(tmp / "skills")
    skills._VERSIONS_DIR = str(tmp / "skills" / "_versions")
    skills._LEARNING_LOG_PATH = str(tmp / "learning_log.json")
    (tmp / "skills" / "_versions").mkdir(parents=True, exist_ok=True)


def _seed_log(entries: list[dict]) -> None:
    Path(skills._LEARNING_LOG_PATH).write_text(
        json.dumps(entries, ensure_ascii=False), encoding="utf-8"
    )


def _log_entry(event_type: str, name: str, ts: str) -> dict:
    return {"ts": ts, "type": event_type, "skill": name, "reason": "test", "metadata": {}}


def _stamp(offset_seconds: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - offset_seconds))


def _check_meta_detection() -> None:
    """Les 17 doublons reellement produits doivent tous etre reconnus comme meta."""
    for name in (
        "garde-fou-consolidation-repetee",
        "revue-automatique-learning-log",
        "dedup-consolidation-loop",
        "anti-consolidation-repetee",
        "dedoublonnage-consolidation-log",
        "revue-auto-learning-log-garde-fou",
        "consolidation-avec-cooldown",
    ):
        assert skills._is_meta_skill(name, ""), name
    # Une description meta seule suffit, meme avec un nom neutre.
    assert skills._is_meta_skill("nom-neutre", "Revoir le journal d'apprentissage de Marvin")
    # Les competences metier ne doivent jamais etre bloquees.
    for name, desc in (
        ("diagnostic-imprimante-reseau", "Depanner une imprimante reseau"),
        ("devis-client-koios", "Preparer un devis client"),
        ("calibration-ecran-couleur", "Calibrer un ecran externe"),
    ):
        assert not skills._is_meta_skill(name, desc), name


def _check_duplicate_detection() -> None:
    existing = [
        {"name": "anti-consolidation-repetee",
         "description": "Detecter et neutraliser les consolidations repetees sur une competence stable."},
        {"name": "diagnostic-imprimante", "description": "Depanner une imprimante reseau qui ne repond plus."},
    ]
    assert skills._duplicates_existing_skill("anti-consolidation-repetee", "autre", existing)
    # Insensible aux accents et a la casse.
    assert skills._duplicates_existing_skill("ANTI-Consolidation-Repetee", "autre", existing)
    assert skills._duplicates_existing_skill(
        "nom-neuf",
        "Detecter et neutraliser les consolidations repetees sur une competence stable.",
        existing,
    )
    assert not skills._duplicates_existing_skill(
        "calibration-ecran", "Calibrer la colorimetrie d un ecran DisplayPort externe", existing
    )
    assert not skills._duplicates_existing_skill("quoi-que-ce-soit", "peu importe", [])


def _check_cooldown() -> None:
    _seed_log([_log_entry("consolidate", "x", _stamp(60))])
    assert skills._consolidation_on_cooldown() is True, "consolidation recente => cooldown"

    _seed_log([_log_entry("consolidate", "x", _stamp(skills.CONSOLIDATION_COOLDOWN_SECONDS + 600))])
    assert skills._consolidation_on_cooldown() is False, "consolidation ancienne => libre"

    _seed_log([_log_entry("create", "x", _stamp(60))])
    assert skills._consolidation_on_cooldown() is False, "une creation n est pas une consolidation"

    _seed_log([])
    assert skills._consolidation_on_cooldown() is False, "journal vide => libre"

    # Un horodatage corrompu ne doit jamais bloquer le worker.
    _seed_log([{"ts": "pas-une-date", "type": "consolidate", "skill": "x", "reason": ""}])
    assert skills._consolidation_on_cooldown() is False


def _run(coro):
    return asyncio.run(coro)


def _llm(payload: dict):
    captured: dict = {}

    async def generate(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(payload, ensure_ascii=False)

    return generate, captured


def _check_end_to_end() -> None:
    body = "## Objectif\nTrier.\n## Étapes\n1. Lister.\n## Vérification\nOK."
    log = [_log_entry("upgrade", "s", _stamp(7200 + i)) for i in range(4)]

    # 1. Cas nominal : outils inventes retires, competence ecrite.
    _seed_log(log)
    gen, captured = _llm({
        "name": "tri-photos-vacances",
        "description": "Trier et renommer des photos par date de prise de vue",
        "triggers": ["trier mes photos"],
        "tools": ["file_find", "learning-log", "bash"],
        "body": body,
    })
    out = _run(skills.review_and_consolidate_learnings(gen, "s", tool_names=REAL_TOOLS))
    assert out == {"consolidated": "tri-photos-vacances"}, out
    assert "Outils réellement disponibles" in captured["prompt"]
    assert "NE PROPOSE RIEN" in captured["prompt"]
    written = next(s for s in skills.list_skills() if s["name"] == "tri-photos-vacances")
    assert written["tools"] == ["file_find"], written["tools"]

    # 2. Cooldown : la consolidation precedente vient d avoir lieu.
    gen2, _ = _llm({"name": "autre-competence", "description": "Autre chose",
                    "triggers": ["x"], "tools": [], "body": body})
    assert _run(skills.review_and_consolidate_learnings(gen2, "s", tool_names=REAL_TOOLS)) is None

    # 3. Sujet meta refuse, meme hors cooldown.
    _seed_log(log)
    gen3, _ = _llm({"name": "garde-anti-consolidation", "description": "Eviter les consolidations repetees",
                    "triggers": ["x"], "tools": [], "body": body})
    assert _run(skills.review_and_consolidate_learnings(gen3, "s", tool_names=REAL_TOOLS)) is None
    assert not any(s["name"] == "garde-anti-consolidation" for s in skills.list_skills())
    assert any(e["type"] == "consolidate_refused" for e in skills.get_learning_log(20))

    # 4. Doublon refuse.
    _seed_log(log)
    gen4, _ = _llm({"name": "tri-photos-vacances-2",
                    "description": "Trier et renommer des photos par date de prise de vue",
                    "triggers": ["x"], "tools": [], "body": body})
    assert _run(skills.review_and_consolidate_learnings(gen4, "s", tool_names=REAL_TOOLS)) is None

    # 5. Journal trop court : rien ne se declenche.
    _seed_log([_log_entry("upgrade", "s", _stamp(9000))])
    gen5, _ = _llm({"name": "peu-importe", "description": "x", "triggers": ["x"], "tools": [], "body": body})
    assert _run(skills.review_and_consolidate_learnings(gen5, "s", tool_names=REAL_TOOLS)) is None


def main() -> int:
    original = (skills._SKILLS_DIR, skills._VERSIONS_DIR, skills._LEARNING_LOG_PATH)
    with tempfile.TemporaryDirectory() as raw:
        try:
            _isolate(Path(raw))
            _check_meta_detection()
            _check_duplicate_detection()
            _check_cooldown()
            _check_end_to_end()
        finally:
            skills._SKILLS_DIR, skills._VERSIONS_DIR, skills._LEARNING_LOG_PATH = original
    print(
        "Consolidation Guards OK - cooldown, sujets meta, doublons refuses "
        "et outils inexistants filtres."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
