"""Canonical language-tag contracts shared by Agent Canvas schemas."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints


_BCP47_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


def canonicalize_bcp47_tag(value: str) -> str:
    """Validate and normalize a bounded structural BCP 47 language tag."""

    if not _BCP47_PATTERN.fullmatch(value):
        raise ValueError("Response locale must be a valid BCP 47 language tag.")
    parts = value.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


BCP47Tag = Annotated[
    str,
    StringConstraints(pattern=_BCP47_PATTERN.pattern, max_length=64),
    AfterValidator(canonicalize_bcp47_tag),
]
