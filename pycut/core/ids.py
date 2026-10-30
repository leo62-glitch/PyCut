"""Identifier helpers. CapCut drafts use upper-case UUID4 strings."""
import uuid


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def short_id(full: str) -> str:
    return full[:8]
