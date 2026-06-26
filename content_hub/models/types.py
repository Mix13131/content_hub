from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql


JSONB = postgresql.JSONB(astext_type=postgresql.TEXT()).with_variant(JSON(), "sqlite")
