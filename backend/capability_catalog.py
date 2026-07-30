"""Catalogue dérivé des contrats d'outils, sans seconde source de vérité.

La recherche classe et décrit des capacités. Elle ne choisit ni n'exécute jamais
un outil à la place du modèle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tool_capability_ranking import build_catalog, rank_capabilities
from capability_discovery import (
    DISCOVERY_SCHEMA_VERSION,
    discovery_enabled,
    parameter_text,
    profile_for,
)


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    name: str
    namespace: str
    summary: str
    required_arguments: tuple[str, ...]
    parameter_names: tuple[str, ...]
    title: str = ""
    aliases: tuple[str, ...] = ()
    use_when: tuple[str, ...] = ()
    do_not_use_when: tuple[str, ...] = ()
    related_tools: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "summary": self.summary,
            "required_arguments": list(self.required_arguments),
            "parameter_names": list(self.parameter_names),
            "title": self.title,
            "aliases": list(self.aliases),
            "use_when": list(self.use_when),
            "do_not_use_when": list(self.do_not_use_when),
            "related_tools": list(self.related_tools),
        }


def _namespace(name: str) -> str:
    parts = [part for part in name.split("_") if part]
    return parts[0] if parts else "general"


class CapabilityCatalog:
    """Vue immuable du registre de schémas fourni par l'application."""

    def __init__(
        self,
        specifications: Iterable[dict[str, Any]],
        *,
        enhanced: bool | None = None,
    ) -> None:
        self._enhanced = discovery_enabled() if enhanced is None else bool(enhanced)
        specs: dict[str, dict[str, Any]] = {}
        descriptors: dict[str, CapabilityDescriptor] = {}
        ordered_specs: list[dict[str, Any]] = []
        discovery_documents: dict[str, str] = {}
        exclusion_documents: dict[str, str] = {}
        for specification in specifications:
            function = specification.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            if name in specs:
                raise ValueError(f"Capacité dupliquée : {name}")
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                parameters = {}
            properties = parameters.get("properties")
            if not isinstance(properties, dict):
                properties = {}
            required = parameters.get("required")
            if not isinstance(required, list):
                required = []
            summary = " ".join(str(function.get("description") or "").split())[:800]
            profile = profile_for(name) if self._enhanced else profile_for("")
            related = tuple(
                item for item in profile.related_tools if item and item != name
            )
            descriptor = CapabilityDescriptor(
                name=name,
                namespace=_namespace(name),
                summary=summary,
                required_arguments=tuple(str(item) for item in required),
                parameter_names=tuple(str(item) for item in properties),
                title=profile.title if self._enhanced else "",
                aliases=profile.aliases if self._enhanced else (),
                use_when=profile.use_when if self._enhanced else (),
                do_not_use_when=profile.do_not_use_when if self._enhanced else (),
                related_tools=related if self._enhanced else (),
            )
            specs[name] = specification
            descriptors[name] = descriptor
            ordered_specs.append(specification)
            if self._enhanced:
                discovery_documents[name] = profile.search_document(
                    name,
                    summary,
                    parameter_text(function),
                )
                exclusion_documents[name] = " ".join(profile.do_not_use_when)
        self._specifications = specs
        self._descriptors = descriptors
        self._ranking_catalog = build_catalog(
            ordered_specs,
            discovery_documents,
            exclusion_documents,
        )

    def __len__(self) -> int:
        return len(self._specifications)

    def describe(self, name: str) -> CapabilityDescriptor | None:
        return self._descriptors.get(str(name or "").strip())

    def exact_specifications(self, names: Iterable[str]) -> list[dict[str, Any]]:
        """Retourne uniquement les schémas exacts demandés, dans l'ordre fourni."""
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_name in names:
            name = str(raw_name or "").strip()
            if name in seen:
                continue
            specification = self._specifications.get(name)
            if specification is not None:
                result.append(specification)
                seen.add(name)
        return result

    def search(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        normalized_query = " ".join(str(query or "").split())
        if not normalized_query:
            raise ValueError("La recherche de capacité est vide.")
        if len(normalized_query) > 2_000:
            raise ValueError("La recherche de capacité dépasse 2 000 caractères.")
        bounded_limit = max(1, min(int(limit), 20))

        exact_name = normalized_query.strip().lower().replace(".", "_")
        names: list[str] = []
        if exact_name in self._specifications:
            names.append(exact_name)
        for name, _score in rank_capabilities(
            normalized_query,
            self._ranking_catalog,
            limit=bounded_limit,
            min_score=1.5,
        ):
            if name not in names:
                names.append(name)
            if len(names) >= bounded_limit:
                break
        return {
            "query": normalized_query,
            "count": len(names),
            "catalog_size": len(self),
            "candidates": [
                self._descriptors[name].public_dict()
                for name in names
            ],
            "advisory_only": True,
            "discovery_schema": (
                DISCOVERY_SCHEMA_VERSION if self._enhanced else "legacy"
            ),
        }
