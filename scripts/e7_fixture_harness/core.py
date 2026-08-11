from __future__ import annotations

from typing import Any, Mapping


class HarnessComponent:
    __slots__ = ("component", "adapter", "operations", "uses_tool_registry", "public_tools_used")

    def __init__(self, component: str, adapter: str, operations: tuple[str, ...]) -> None:
        self.component = component
        self.adapter = adapter
        self.operations = operations
        self.uses_tool_registry = False
        self.public_tools_used: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


class FixturePlan:
    __slots__ = (
        "contract_id", "tool", "action", "e7_class", "surface_profile", "isolation",
        "symbolic_payload", "setup", "observer", "oracle", "recovery", "allowed_delta",
        "forbidden_deltas", "execution_authorized", "host_execution_forbidden",
    )

    def __init__(
        self,
        *,
        contract_id: str,
        tool: str,
        action: str,
        e7_class: str,
        surface_profile: str,
        isolation: str,
        symbolic_payload: Mapping[str, Any],
        setup: HarnessComponent,
        observer: HarnessComponent,
        oracle: HarnessComponent,
        recovery: HarnessComponent,
        allowed_delta: str,
        forbidden_deltas: tuple[str, ...],
    ) -> None:
        self.contract_id = contract_id
        self.tool = tool
        self.action = action
        self.e7_class = e7_class
        self.surface_profile = surface_profile
        self.isolation = isolation
        self.symbolic_payload = dict(symbolic_payload)
        self.setup = setup
        self.observer = observer
        self.oracle = oracle
        self.recovery = recovery
        self.allowed_delta = allowed_delta
        self.forbidden_deltas = forbidden_deltas
        self.execution_authorized = False
        self.host_execution_forbidden = True

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__slots__:
            value = getattr(self, name)
            result[name] = value.to_dict() if isinstance(value, HarnessComponent) else value
        return result


def component(name: str, adapter: str, *operations: str) -> HarnessComponent:
    if not operations:
        raise ValueError("Un composant de fixture doit déclarer au moins une opération.")
    return HarnessComponent(name, adapter, tuple(operations))


def validate_plan(plan: FixturePlan) -> None:
    if plan.execution_authorized or not plan.host_execution_forbidden:
        raise ValueError("Une fixture pilote ne peut autoriser aucune exécution.")
    for part in (plan.setup, plan.observer, plan.oracle, plan.recovery):
        if part.uses_tool_registry or part.public_tools_used:
            raise ValueError(f"Couplage interdit au runtime Marvin: {part.component}")
    if plan.e7_class == "R" and "exact" not in plan.recovery.operations:
        raise ValueError("Une fixture R doit déclarer une restauration exacte indépendante.")
    if plan.e7_class == "N" and plan.recovery.adapter != "none":
        raise ValueError("Une fixture N ne possède pas de récupération métier.")
