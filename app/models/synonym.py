"""Pydantic models for the managed synonyms API (ES ``_synonyms``)."""
from typing import Optional

from pydantic import BaseModel


class SynonymSetIn(BaseModel):
    """Body to create/replace a synonym set."""
    description: Optional[str] = None
    synonyms: list[str]            # rule strings, e.g. "ucb, united commercial bank" or "rfl => rfl plastics"


class SynonymRuleIn(BaseModel):
    """Body to upsert a single rule within a set."""
    synonyms: str                  # the rule string


class SynonymSetOut(BaseModel):
    id: str
    description: Optional[str] = None
    synonyms: list[str]


class SynonymRuleOut(BaseModel):
    id: Optional[str] = None
    synonyms: str
