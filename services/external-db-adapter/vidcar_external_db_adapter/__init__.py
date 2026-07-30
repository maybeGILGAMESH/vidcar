"""Importable wrapper for the hyphenated service directory."""
from packages.common.external_database import (
    ExternalDatabaseAdapter,
    ExternalDatabaseNotConfigured,
    StubExternalDatabaseAdapter,
)

__all__ = [
    "ExternalDatabaseAdapter",
    "ExternalDatabaseNotConfigured",
    "StubExternalDatabaseAdapter",
]
