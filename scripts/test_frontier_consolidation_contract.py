"""Valide le contrat global de consolidation de Marvin sans démarrer le backend."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "MARVIN-FRONTIER-CONSOLIDATION.md"
EXPECTED_DOMAINS = {
    "runner", "sessions", "tools", "models", "memory", "coding", "isolation",
    "persistence", "api", "workers", "observability", "security", "frontend",
    "avatar", "voice", "installer",
}
ALLOWED_STATUSES = {"verified", "partial", "not_audited", "blocked"}
REQUIRED_SECTIONS = {
    "## 1. Objet et règle de preuve",
    "## 2. Référentiel comparé",
    "## 3. Décision d'architecture globale",
    "## 4. Matrice exhaustive",
    "## 5. Gate obligatoire par tranche",
    "## 6. Rollback standard",
    "## 7. Critère de clôture globale",
}
REQUIRED_REFERENCES = {
    "openai.github.io/openai-agents-python",
    "anthropic.com/engineering/building-effective-agents",
    "anthropic.com/engineering/demystifying-evals-for-ai-agents",
    "adk.dev/sessions",
    "genai.owasp.org/initiatives/agentic-security-initiative",
    "opentelemetry.io/docs/specs/semconv/gen-ai",
    "opentelemetry.io/docs/specs/otel/logs/data-model",
    "cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet",
    "csrc.nist.gov/pubs/sp/800/92/r1/ipd",
    "nist.gov/itl/ai-risk-management-framework",
    "learn.microsoft.com/windows/apps/package-and-deploy",
}


class ContractError(RuntimeError):
    pass


def parse_matrix(text: str) -> dict[str, str]:
    match = re.search(r"<!-- frontier-matrix\s*(.*?)\s*-->", text, flags=re.DOTALL)
    if not match:
        raise ContractError("Le manifeste frontier-matrix est absent.")
    result: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 2:
            raise ContractError(f"Ligne de matrice invalide : {line!r}")
        domain, status = parts
        if domain in result:
            raise ContractError(f"Domaine dupliqué : {domain}")
        if status not in ALLOWED_STATUSES:
            raise ContractError(f"Statut invalide pour {domain} : {status}")
        result[domain] = status
    return result


def run() -> dict[str, int]:
    if not CONTRACT.is_file():
        raise ContractError(f"Contrat absent : {CONTRACT}")
    text = CONTRACT.read_text(encoding="utf-8-sig")
    missing_sections = sorted(section for section in REQUIRED_SECTIONS if section not in text)
    if missing_sections:
        raise ContractError(f"Sections obligatoires absentes : {missing_sections}")
    missing_references = sorted(ref for ref in REQUIRED_REFERENCES if ref not in text)
    if missing_references:
        raise ContractError(f"Références primaires absentes : {missing_references}")
    matrix = parse_matrix(text)
    missing = sorted(EXPECTED_DOMAINS - set(matrix))
    unknown = sorted(set(matrix) - EXPECTED_DOMAINS)
    if missing or unknown:
        raise ContractError(f"Couverture invalide : absents={missing}, inconnus={unknown}")
    if "au moins deux approches" not in text.lower():
        raise ContractError("La comparaison de deux approches doit rester obligatoire.")
    if "amélioration proactive" not in text.lower():
        raise ContractError("L'amélioration proactive doit rester obligatoire par tranche.")
    for requirement in (
        "impact de journalisation obligatoire",
        "rotation",
        "rétention",
        "test de non-divulgation",
        "MARVIN-LOGGING-POLICY.md",
    ):
        if requirement not in text:
            raise ContractError(f"Exigence de journalisation absente : {requirement}")
    if "git apply --cached --check --reverse" not in text:
        raise ContractError("Le contrôle de réversibilité du patch doit rester documenté.")
    if "`git revert <commit>`" not in text:
        raise ContractError("Le rollback atomique après commit doit rester documenté.")
    return {
        "domains": len(matrix),
        "verified": sum(status == "verified" for status in matrix.values()),
        "partial": sum(status == "partial" for status in matrix.values()),
    }


def main() -> int:
    try:
        result = run()
    except (OSError, ContractError) as exc:
        print(f"ECHEC contrat frontier : {exc}")
        return 1
    print(
        "Contrat frontier OK - "
        f"{result['domains']} domaines | {result['verified']} vérifiés | "
        f"{result['partial']} partiels"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
