"""
extract_ifc_data.py
====================
Dynamic extraction of compliance-relevant data from any IFC file that
follows the same pattern as our generated model: 1 IfcSpace, walls,
and 1 IfcWindow installed via an IfcOpeningElement.

DESIGN PRINCIPLE: no hardcoded GlobalIds or names. Elements are found
by IFC TYPE (IfcSpace, IfcWindow) and by RELATIONSHIP (window -> opening
-> hosting wall), so this works on any IFC model with this structure --
not just the one generate_ifc.py produces.

Every extractor function returns None (not a crash) when a value is
missing, so the caller can decide CANNOT_BE_EVALUATED for that field.
"""

import os
import ifcopenshell
import ifcopenshell.geom
import numpy as np

DEFAULT_PATH = os.path.join("data", "generated", "compliant_model.ifc")


def _get_qto_value(element, qto_name, quantity_name):
    """
    Safely reads one quantity value (e.g. NetFloorArea) from a named
    Qto attached to an element. Returns None if the Qto or the specific
    quantity isn't present -- never raises.
    """
    for rel in getattr(element, "IsDefinedBy", []):
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        if not pset.is_a("IfcElementQuantity") or pset.Name != qto_name:
            continue
        for q in pset.Quantities:
            if q.Name == quantity_name:
                if q.is_a("IfcQuantityArea"):
                    return q.AreaValue
                if q.is_a("IfcQuantityLength"):
                    return q.LengthValue
    return None


def _get_world_bbox(model, element):
    """
    Returns (min_xyz, max_xyz) of an element's geometry in world
    coordinates, or None if it has no representation to measure.
    """
    if element.Representation is None:
        return None
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except RuntimeError:
        return None
    verts = np.array(shape.geometry.verts).reshape(-1, 3)
    return verts.min(axis=0), verts.max(axis=0)


def extract_room_data(model):
    """
    Finds the first IfcSpace (by TYPE, not by name) and extracts:
    name, GlobalId, width, length (from geometry bbox), floor_area
    (preferring the explicit Qto, falling back to bbox width*length).
    """
    spaces = model.by_type("IfcSpace")
    if not spaces:
        return None  # no room found at all -> caller treats as CANNOT_BE_EVALUATED

    room = spaces[0]  # dynamic: just "the" room, no hardcoded name assumed

    floor_area = _get_qto_value(room, "Qto_SpaceBaseQuantities", "NetFloorArea")

    bbox = _get_world_bbox(model, room)
    width = length = None
    if bbox is not None:
        min_xyz, max_xyz = bbox
        width = round(float(max_xyz[0] - min_xyz[0]), 4)
        length = round(float(max_xyz[1] - min_xyz[1]), 4)
        if floor_area is None:
            floor_area = round(width * length, 4)

    return {
        "name": room.Name,
        "global_id": room.GlobalId,
        "width_m": width,
        "length_m": length,
        "floor_area_m2": floor_area,
    }


def extract_window_data(model):
    """
    Finds the first IfcWindow (by TYPE) and extracts: name, GlobalId,
    width, height, area (preferring explicit Qto, falling back to
    geometry bbox), and sill_height_m via the standard IFC relationship
    chain: IfcWindow.FillsVoids -> IfcOpeningElement -> its Z placement
    relative to the storey elevation.

    Returns sill_height_m = None if the window has no proper opening
    relationship (this is exactly the failure mode we hit with the
    Revit export -- it must degrade gracefully, not crash).
    """
    windows = model.by_type("IfcWindow")
    if not windows:
        return None

    window = windows[0]

    width = _get_qto_value(window, "Qto_WindowBaseQuantities", "Width")
    height = _get_qto_value(window, "Qto_WindowBaseQuantities", "Height")
    area = _get_qto_value(window, "Qto_WindowBaseQuantities", "Area")

    bbox = _get_world_bbox(model, window)
    if bbox is not None:
        min_xyz, max_xyz = bbox
        if width is None:
            width = round(float(max_xyz[0] - min_xyz[0]), 4)
        if height is None:
            height = round(float(max_xyz[2] - min_xyz[2]), 4)
        if area is None and width is not None and height is not None:
            area = round(width * height, 4)

    sill_height = _extract_sill_height(model, window)

    return {
        "name": window.Name,
        "global_id": window.GlobalId,
        "width_m": width,
        "height_m": height,
        "area_m2": area,
        "sill_height_m": sill_height,
    }


def _extract_sill_height(model, window):
    """
    Reliable method (validated against our own generated model):
    window -> FillsVoids -> IfcOpeningElement -> placement Z,
    relative to the storey's elevation.

    Returns None (not an exception) if any link in the chain is
    missing -- e.g. a window placed without a proper opening, which
    is exactly the situation we hit with the Revit-exported model.
    """
    if not window.FillsVoids:
        return None  # no opening relationship at all

    opening = window.FillsVoids[0].RelatingOpeningElement
    if opening.ObjectPlacement is None:
        return None

    try:
        opening_z = opening.ObjectPlacement.RelativePlacement.Location.Coordinates[2]
    except (AttributeError, IndexError):
        return None

    storey = model.by_type("IfcBuildingStorey")
    storey_elevation = storey[0].Elevation if storey and storey[0].Elevation else 0.0

    return round(opening_z - storey_elevation, 4)


def extract_all(ifc_path):
    """
    Top-level entry point: opens the IFC file and returns a single
    dict with everything downstream compliance-checking code needs.
    """
    model = ifcopenshell.open(ifc_path)
    return {
        "source_file": ifc_path,
        "schema": model.schema,
        "room": extract_room_data(model),
        "window": extract_window_data(model),
    }


if __name__ == "__main__":
    import sys
    import json

    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    data = extract_all(path)
    print(json.dumps(data, indent=2, ensure_ascii=False))