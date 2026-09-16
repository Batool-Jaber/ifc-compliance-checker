"""
validation/field_paths.py
==========================
Single source of truth for which extracted-data fields a Condition may
be checked against via the generic validation engine.

This list mirrors EXACTLY what extract_ifc_data.py's extract_all()
produces (room dict + window dict). It is a deliberately closed,
hardcoded list -- not derived dynamically from the dicts at runtime --
so a field can only be added here as a conscious code change, never
by accident or by whatever IfcOpenShell happens to return.

Used by:
  - admin/services/validation.py (server-side rejection of any
    field_path value not in this list)
  - templates/admin/condition_new.html (dropdown options, rendered
    from this same list -- never hand-typed twice)
  - validation/generic_engine.py (to know which dict + key to read)

SECURITY NOTE: resolve_field_path() below is a pure dict lookup. It
never evaluates a string as code and never accepts anything outside
KNOWN_FIELD_PATHS. This is what keeps engineer-submitted "new
condition" proposals exactly as safe as the 3 original hardcoded
checks -- no proposal can ever cause arbitrary code to run.
"""

# Each entry: "room.<key>" or "window.<key>", matching a key that
# extract_ifc_data.py's extract_all() actually produces.
KNOWN_FIELD_PATHS = [
    "room.width_m",
    "room.length_m",
    "room.floor_area_m2",
    "window.width_m",
    "window.height_m",
    "window.area_m2",
    "window.sill_height_m",
    "window.area_ratio_percent",  # derived field -- added to extract_ifc_data.py in Step 2
]


def is_known_field_path(value: str) -> bool:
    """True iff value is one of the closed set of allowed field paths.
    Used by admin/services/validation.py to reject anything else,
    server-side, regardless of what the client sent."""
    return value in KNOWN_FIELD_PATHS


def resolve_field_path(field_path: str, room: dict | None, window: dict | None):
    """
    Looks up the value for a KNOWN field_path in already-extracted
    room/window dicts. Returns None (never raises) if:
      - field_path isn't in KNOWN_FIELD_PATHS,
      - the relevant source dict (room or window) is None,
      - or the key is missing/None in that dict.
    This is a pure lookup -- no eval(), no expression parsing.
    """
    if field_path not in KNOWN_FIELD_PATHS:
        return None

    source_name, _, key = field_path.partition(".")
    source = {"room": room, "window": window}.get(source_name)
    if source is None:
        return None
    return source.get(key)