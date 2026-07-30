"""Checksum and immutable manifest helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import BinaryIO, Iterable


class ChecksumMismatch(ValueError):
    pass


def sha256_stream(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return sha256_stream(stream)


def verify_sha256(chunks: Iterable[bytes], expected: str) -> None:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise ChecksumMismatch(f"sha256 mismatch: expected {expected}, got {actual}")


def canonical_manifest_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def manifest_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_manifest_bytes(payload)).hexdigest()


def validate_model_reference(version: str, sha256: str, stage: str) -> None:
    if version.lower() == "latest":
        raise ValueError("model version 'latest' is forbidden")
    if stage != "approved":
        raise ValueError("production models must be in approved stage")
    if len(sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in sha256):
        raise ValueError("model sha256 is invalid")
