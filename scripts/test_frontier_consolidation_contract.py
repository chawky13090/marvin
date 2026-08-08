"""Valide le contrat global de consolidation de Marvin sans démarrer le backend."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "MARVIN-FRONTIER-CONSOLIDATION.md"
SECURITY_REGISTER = ROOT / "SECURITY-DEBT-REGISTER.md"
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
    "## 8. Exigences non négociables consolidées",
    "## 9. Feuille de route d'exécution révisée",
    "## 10. Preuves minimales par grande capacité",
    "## 11. Règle d'évolution du plan",
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
    if not all(
        marker in text
        for marker in ("16 JSONL classifiés", "preuves chaînées")
    ):
        raise ContractError("La preuve d'inventaire des persistances JSONL doit rester visible.")
    for requirement in (
        "revue de sécurité obligatoire",
        "Toute dette restante doit être inventoriée, bornée, justifiée et planifiée",
        "aucune dette de sécurité ne peut être ignorée",
        "elle ne peut pas être masquée par un",
    ):
        if requirement not in text:
            raise ContractError(f"Exigence de sécurité globale absente : {requirement}")
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
    for requirement in (
        "Ultra débridé reste strictement Cloud-only",
        "Council utilise cinq familles de modèles Cloud distinctes",
        "aucune limite arbitraire de 120 minutes",
        "demande de code peut être saisie directement dans le chat général ou dans Code",
        "VM Debian",
        "VM Windows",
        "preuves métier utiles sont conservées plus longtemps",
        "harness",
        "avatar de bureau",
        "boucle de Möbius 3D",
        "voix est sérialisée",
        "installateur final est Windows-first, en un clic",
    ):
        if requirement not in text:
            raise ContractError(f"Exigence produit consolidée absente : {requirement}")
    if not SECURITY_REGISTER.is_file():
        raise ContractError("Le registre central de dette de sécurité est absent.")
    security_text = SECURITY_REGISTER.read_text(encoding="utf-8-sig")
    for requirement in (
        "SEC-001",
        "SEC-002",
        "SEC-003",
        "SEC-004",
        "SEC-005",
        "Critère de fermeture",
    ):
        if requirement not in security_text:
            raise ContractError(
                f"Le registre de sécurité ne contient pas l'exigence : {requirement}"
            )
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
