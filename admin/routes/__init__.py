"""
admin/routes/
=============
One module per feature (auth, conditions, proposals, users, audit).
Each module attaches its routes to `admin_bp` (imported from admin/
__init__.py) as a side effect of being imported -- see admin/__init__.py
for the import order and why it matters.
"""