"""SQLAlchemy models. Importing them here registers every table on Base.metadata so
Alembic autogenerate and create_all see the full schema from one place.
"""

from app.models.user import User

__all__ = ["User"]
