"""Bitemporal base — `valid_at` + `observed_at` on every fact.

The one irreversible decision from the research:
  - `valid_at`: when this fact represents truth in the world (use the broker's
                timestamp if it stamps the data; else the fetch time).
  - `observed_at`: when we recorded it (always set on creation; never changes).

Two ingestions of the same `valid_at` with different `observed_at` = correction
history. Persistence engine (Postgres-now / Iceberg-later) is a downstream
milestone — at v0 the columns simply exist on every entity, free.
"""
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Bitemporal(BaseModel):
    """Every entity in sq_schema inherits this. Two timestamps, both required."""

    model_config = ConfigDict(
        frozen=False,           # snapshots may be mutated mid-construction
        extra="forbid",         # surface typos at the adapter boundary, not at runtime
        arbitrary_types_allowed=False,
    )

    valid_at: datetime = Field(default_factory=_now_utc)
    observed_at: datetime = Field(default_factory=_now_utc)
