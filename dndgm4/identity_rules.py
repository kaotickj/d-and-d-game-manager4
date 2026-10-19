"""Flexible demographic details for D&D 3.5 PCs, NPCs and monsters.

Age is stored as a description, not assumed to be human years. The SRD aging
effects are NOT auto-applied unless a separate race-specific rule exists.
"""


def identity_text(value: str, field: str, *, maximum: int = 80) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    cleaned = value.strip()
    if len(cleaned) > maximum or any(c in cleaned for c in "\r\n"):
        raise ValueError(f"{field} must be one line, up to {maximum} characters.")
    return cleaned
