"""Projection OpenAPI de la garde de session LAN appliquée par middleware."""

from __future__ import annotations

from typing import Any

from fastapi.openapi.utils import get_openapi

from lan_access import PUBLIC_PATHS, SESSION_COOKIE


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def install_access_contract(app) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )
        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})["MarvinLanSession"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": SESSION_COOKIE,
            "description": (
                "Cookie HttpOnly signé obtenu par jumelage LAN. "
                "La boucle locale constitue une frontière de confiance distincte."
            ),
        }
        components.setdefault("schemas", {})["MarvinAccessError"] = {
            "type": "object",
            "required": ["detail"],
            "properties": {"detail": {"type": "string"}},
            "additionalProperties": False,
        }
        error_response = {
            "description": "Session LAN absente, expirée ou invalide.",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MarvinAccessError"}
                }
            },
        }
        csrf_response = {
            "description": "Origine ou jeton CSRF refusé.",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MarvinAccessError"}
                }
            },
        }
        for path, path_item in schema.get("paths", {}).items():
            for method, operation in path_item.items():
                if method not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                if path in PUBLIC_PATHS:
                    operation["security"] = []
                    if path.endswith("/pair"):
                        operation.setdefault("responses", {}).setdefault(
                            "401", error_response
                        )
                    continue
                operation["security"] = [{"MarvinLanSession": []}]
                operation.setdefault("responses", {}).setdefault("401", error_response)
                if method in {"post", "put", "patch", "delete"}:
                    operation["responses"].setdefault("403", csrf_response)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
