"""Fail-closed interface for the not-yet-configured external database."""
from typing import Any, Protocol


class ExternalDatabaseAdapter(Protocol):
    def healthcheck(self) -> dict[str, Any]: ...
    def fetch_reference_data(self, query: dict[str, Any]) -> list[dict[str, Any]]: ...
    def publish_result(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ExternalDatabaseNotConfigured(RuntimeError):
    pass


class StubExternalDatabaseAdapter:
    def healthcheck(self) -> dict[str, Any]:
        return {"status": "not_configured", "state": "dns_nxdomain", "retryable": False}

    def fetch_reference_data(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def publish_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise ExternalDatabaseNotConfigured("external database writes are disabled")
