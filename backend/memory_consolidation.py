"""
Consolidation périodique de la mémoire générale (v2.115), même esprit que le Learning
Log des compétences (skills.py, v2.95) mais pour les souvenirs (memory_save/memory_list).
Mem0 (référence 2026 pour la mémoire d'agent) documente ce pattern comme ce qui transforme
une mémoire qui ne fait qu'accumuler en un système qui reste utile à long terme :
dédoublonnage continu des souvenirs redondants.

Volontairement DÉTERMINISTE, pas piloté par un LLM : `tools.py::execute_memory_save` fait
déjà un dédoublonnage par recouvrement de sous-chaîne AU MOMENT de l'enregistrement (ne
compare qu'aux souvenirs déjà en base à cet instant précis). Cette passe périodique
applique la MÊME logique de comparaison à TOUTES les paires de souvenirs existants, pour
rattraper les doublons qui ont pu passer entre les mailles (créés dans un ordre différent,
importés en base, etc.). Rester déterministe (comparaison de texte, pas de jugement LLM)
évite le risque qu'un modèle fusionne à tort deux souvenirs qui se ressemblent mais sont
en réalité différents.
"""
import database as db


def _overlap_score(a: str, b: str) -> float:
    """Même heuristique que execute_memory_save (tools.py) : recouvrement de sous-chaîne
    normalisé, symétrique. 1.0 = identique, 0.0 = aucun recouvrement significatif."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) > 20 and len(b) > 20 and (a in b or b in a):
        return min(len(a), len(b)) / max(len(a), len(b))
    return 0.0


def consolidate_memories(dry_run: bool = False, threshold: float = 0.75) -> dict:
    """Fusionne les souvenirs quasi-identiques (même catégorie, fort recouvrement de
    texte). Garde toujours le plus LONG/détaillé des deux, supprime l'autre. Best-effort :
    ne lève jamais. `dry_run=True` calcule les fusions sans rien supprimer (aperçu)."""
    try:
        memories = db.get_memories()
    except Exception as e:
        return {"error": str(e)}

    by_category: dict[str, list[dict]] = {}
    for m in memories:
        by_category.setdefault(m.get("category") or "fact", []).append(m)

    merges = []
    to_delete = set()
    for category, items in by_category.items():
        for i in range(len(items)):
            if items[i]["id"] in to_delete:
                continue
            for j in range(i + 1, len(items)):
                if items[j]["id"] in to_delete:
                    continue
                score = _overlap_score(items[i].get("content", ""), items[j].get("content", ""))
                if score >= threshold:
                    keep, drop = (
                        (items[i], items[j])
                        if len(items[i].get("content", "")) >= len(items[j].get("content", ""))
                        else (items[j], items[i])
                    )
                    merges.append({
                        "category": category,
                        "kept": keep.get("content", ""),
                        "dropped": drop.get("content", ""),
                        "overlap": round(score, 2),
                    })
                    to_delete.add(drop["id"])

    if not dry_run:
        for mid in to_delete:
            try:
                db.delete_memory(mid)
            except Exception:
                pass

    return {
        "success": True,
        "total_before": len(memories),
        "merged_count": len(to_delete),
        "merges": merges,
        "dry_run": dry_run,
    }
