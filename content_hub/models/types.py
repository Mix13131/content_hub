from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql


JSONB = postgresql.JSONB(astext_type=postgresql.TEXT()).with_variant(JSON(), "sqlite")


def enum_values(enum_cls: type) -> list[str]:
    return [item.value for item in enum_cls]
