"""Post-validation d'un résultat d'outil avant diffusion et observabilité."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


DOCUMENT_TOOLS = frozenset(
    {
        "file_create_pdf",
        "document_generate",
        "billing_quote_pdf",
        "file_convert_docx_to_pdf",
    }
)


async def postprocess_tool_result(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    duration_ms: int,
    user_query: str,
    active_model: str,
    dangerous_tools: set[str] | frozenset[str],
    critique_action: Callable[..., Awaitable[str | None]],
    scan_document: Callable[..., list[str]],
    normalize_result: Callable[..., dict[str, Any]] | None = None,
) -> Any:
    """Ajoute le contrat commun, la critique d'action et le scan documentaire.

    Chaque contrôle reste best-effort : une panne d'observateur ne transforme jamais une
    action déjà exécutée en échec utilisateur.
    """
    if isinstance(result, dict):
        try:
            if normalize_result is None:
                from engineering_runtime import normalize_tool_result

                normalize_result = normalize_tool_result
            result = normalize_result(
                tool_name,
                result,
                duration_ms=duration_ms,
            )
        except Exception:
            pass

    if (
        isinstance(result, dict)
        and result.get("requiresConfirmation")
        and tool_name in dangerous_tools
        and user_query
    ):
        try:
            concern = await critique_action(
                user_query,
                tool_name,
                arguments,
                model=active_model,
            )
            if concern:
                result["message"] = (
                    result.get("message", "")
                    + f"\n\n⚠️ Vérification de Marvin : {concern}"
                )
        except Exception:
            pass

    if (
        tool_name in DOCUMENT_TOOLS
        and isinstance(result, dict)
        and result.get("success")
    ):
        document_text = arguments.get("content") or arguments.get("body") or ""
        if isinstance(document_text, str) and document_text:
            try:
                warnings = scan_document(
                    document_text,
                    require_code_fence=False,
                    document_mode=True,
                )
            except Exception:
                warnings = []
            if warnings:
                result["security_warning"] = (
                    "⚠️ Vérification automatique de sécurité — points à relire "
                    "dans ce document avant de l'utiliser :\n"
                    + "\n".join(f"- {warning}" for warning in warnings)
                )
    return result
