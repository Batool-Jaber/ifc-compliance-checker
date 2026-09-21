"""
admin/extensions.py
====================
Single shared Flask-SQLAlchemy instance for the whole admin package.

Kept in its own tiny module (instead of inside models.py or __init__.py)
specifically to avoid circular imports:
  - models.py needs `db` to define its models
  - __init__.py needs `db` to call `db.init_app(app)`
Both can import `db` from here without importing each other.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()