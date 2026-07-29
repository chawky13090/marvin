"""Contrat négatif du routage des résultats d'outils vers les modèles."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cloud_routing
from agent_loop_policy import sensitive_tool_model_switch
from agent_routing import is_sensitive_request
from tools import TOOLS_REGISTRY


LOCAL = "qwen2.5:14b"
CLOUD = "glm-5:cloud"


def _switch(name: str, *, active_model: str = CLOUD, ultra: bool = False):
    return sensitive_tool_model_switch(
        tool_calls=[{"function": {"name": name}}],
        active_model=active_model,
        profile_name="agent",
        local_fallback_model=LOCAL,
        ultra_cloud_only=ultra,
        is_cloud_model=cloud_routing.is_cloud_model,
        is_sensitive_tool=cloud_routing.is_sensitive_tool,
    )


def test_registry_is_fail_closed() -> None:
    assert cloud_routing.PUBLIC_TOOL_NAMES <= set(TOOLS_REGISTRY)
    assert cloud_routing.classify_tool_data("") is cloud_routing.ToolDataClass.PRIVATE
    assert cloud_routing.classify_tool_data("future_unknown_tool") is cloud_routing.ToolDataClass.PRIVATE
    assert all(
        cloud_routing.classify_tool_data(name) in cloud_routing.ToolDataClass
        for name in TOOLS_REGISTRY
    )


def test_public_results_stay_on_cloud() -> None:
    for name in cloud_routing.PUBLIC_TOOL_NAMES:
        assert cloud_routing.is_sensitive_tool(name) is False
        assert _switch(name) is None


def test_private_domains_switch_before_result_reinjection() -> None:
    representatives = {
        "communications": ("email_accounts", "telegram_send"),
        "remote_access": ("ssh_list", "ssh_server_info"),
        "business": ("billing_client_list", "itsm_ticket_list"),
        "personal_state": ("memory_list", "task_list", "note_list"),
        "calendar": ("calendar_list", "event_list"),
        "documents": ("document_list", "file_read", "pdf_read", "xlsx_read"),
        "cloud_storage": ("google_drive_list", "onedrive_list"),
        "device": ("pc_system_info", "win_users_list", "net_inventory_list"),
        "observability": ("bug_log_list", "pc_conversation_trace"),
        "coding": ("code_workspace_status", "git_info"),
    }
    for names in representatives.values():
        for name in names:
            assert name in TOOLS_REGISTRY
            assert cloud_routing.classify_tool_data(name) is cloud_routing.ToolDataClass.PRIVATE
            switch = _switch(name)
            assert switch is not None
            assert switch.model == LOCAL


def test_four_profile_transition_invariants() -> None:
    # Normal et Tout cloud : une sortie privée quitte le Cloud avant réinjection.
    assert _switch("file_read") is not None
    # Hyper : le modèle est déjà local, donc aucune transition n'est nécessaire.
    assert _switch("file_read", active_model=LOCAL) is None
    # Ultra : consentement explicite Cloud-only, aucun repli local silencieux.
    assert _switch("file_read", ultra=True) is None


def test_recent_private_tool_keeps_followup_local() -> None:
    messages = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "file_read"}}],
    }]
    assert is_sensitive_request(messages, "resume cela") is True
    public_messages = [{
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "weather"}}],
    }]
    assert is_sensitive_request(public_messages, "et demain") is False


def test_structured_sensitive_values_are_detected_without_labels() -> None:
    sensitive_samples = (
        "alice@example.org",
        "Authorization: Bearer abcdefghijklmnop",
        "eyJhbGciOiJIUzI1NiJ9.abcdefghijklmno.signature_value",
        "-----BEGIN PRIVATE KEY-----",
        "api_key=super-secret-value",
        "FR7630006000011234567890189",
        r"C:\Users\Alice\Documents\contrat.txt",
        "/home/alice/.ssh/config",
    )
    for sample in sensitive_samples:
        assert cloud_routing.is_sensitive_text(sample), sample
    for public in ("météo à Paris", "2 + 2", "documentation Python officielle"):
        assert cloud_routing.is_sensitive_text(public) is False


def main() -> int:
    test_registry_is_fail_closed()
    test_public_results_stay_on_cloud()
    test_private_domains_switch_before_result_reinjection()
    test_four_profile_transition_invariants()
    test_recent_private_tool_keeps_followup_local()
    test_structured_sensitive_values_are_detected_without_labels()
    print(
        "Model Data Policy OK - 344 outils fail-closed, domaines privés, "
        "quatre profils et historique."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
