"""
generate_ifc.py
================
Generates a small IFC4 model containing exactly:
- 1 IfcBuilding
- 1 IfcBuildingStorey
- 1 enclosed IfcSpace (room)
- 4 IfcWall
- 1 IfcWindow (installed via a proper IfcOpeningElement)

PART 1: Project -> Site -> Building -> Storey skeleton.
PART 2: 4 walls forming a closed rectangle around the room.
PART 3: IfcSpace (room) with explicit NetFloorArea quantity.
PART 4+5: IfcOpeningElement cut into a wall, filled by an IfcWindow.
"""

import os
import ifcopenshell
import ifcopenshell.api
import numpy as np

# ---- Room / wall dimensions (single source of truth for this script) ----
ROOM_WIDTH = 4.0    # metres (interior, X direction)
ROOM_LENGTH = 3.5   # metres (interior, Y direction)  -> 14.0 m^2
WALL_HEIGHT = 3.0    # metres
WALL_THICKNESS = 0.2  # metres

# ---- Window dimensions (installed in Wall_South, centered) ----
WINDOW_WIDTH = 1.5   # metres  -> area = 1.8 m^2 (12.86% of 14.0 m^2, passes >=10% rule)
WINDOW_HEIGHT = 1.2  # metres
SILL_HEIGHT = 0.9    # metres  -> passes the 0.80-1.10 m rule

# ---- Output location ----
OUTPUT_DIR = os.path.join("data", "generated")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "compliant_model.ifc")


def create_skeleton():
    """
    PART 1: Build the base IFC hierarchy.
    Project -> Site -> Building -> Storey, all linked with
    IfcRelAggregates, and SI units (metres) set on the project.
    """
    model = ifcopenshell.file(schema="IFC4")

    project = ifcopenshell.api.run(
        "root.create_entity", model,
        ifc_class="IfcProject", name="IFC Compliance Checker - Sample Project"
    )
    ifcopenshell.api.run(
        "unit.assign_unit", model,
        length={"is_metric": True, "raw": "METERS"}
    )

    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Sample Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Sample Building")
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Ground Floor")

    ifcopenshell.api.run("aggregate.assign_object", model, products=[site], relating_object=project)
    ifcopenshell.api.run("aggregate.assign_object", model, products=[building], relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", model, products=[storey], relating_object=building)

    return model, project, site, building, storey


def create_geometric_contexts(model):
    """
    Required once per model: defines the 3D 'Model' context and the
    'Body' sub-context that wall/window geometry is expressed in.
    """
    model3d = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run(
        "context.add_context", model,
        context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=model3d
    )
    return body


def make_wall(model, body_context, storey, name, length, position, rotation_deg):
    """
    Creates one IfcWall with a rectangular extrusion, placed and rotated
    in world space, and assigns it to the given storey.

    position: [x, y, z] of the wall's start point (its local origin)
    rotation_deg: rotation around Z axis (0 = wall runs along +X)
    """
    wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name=name)

    representation = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=length, height=WALL_HEIGHT, thickness=WALL_THICKNESS
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=wall, representation=representation)

    theta = np.radians(rotation_deg)
    matrix = np.eye(4)
    matrix[0, 0] = np.cos(theta)
    matrix[0, 1] = -np.sin(theta)
    matrix[1, 0] = np.sin(theta)
    matrix[1, 1] = np.cos(theta)
    matrix[:3, 3] = position
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=wall, matrix=matrix)

    ifcopenshell.api.run("spatial.assign_container", model, products=[wall], relating_structure=storey)

    return wall


def create_walls(model, body_context, storey):
    """
    PART 2: Build 4 walls forming a closed rectangle.
    Wall centerlines are offset outward by half the wall thickness so
    that the ENCLOSED INTERIOR is exactly ROOM_WIDTH x ROOM_LENGTH.
    """
    half_t = WALL_THICKNESS / 2

    walls = {
        "south": make_wall(
            model, body_context, storey, "Wall_South",
            length=ROOM_WIDTH + WALL_THICKNESS,
            position=[-half_t, -half_t, 0.0], rotation_deg=0
        ),
        "north": make_wall(
            model, body_context, storey, "Wall_North",
            length=ROOM_WIDTH + WALL_THICKNESS,
            position=[-half_t, ROOM_LENGTH + half_t, 0.0], rotation_deg=0
        ),
        "west": make_wall(
            model, body_context, storey, "Wall_West",
            length=ROOM_LENGTH + WALL_THICKNESS,
            position=[-half_t, -half_t, 0.0], rotation_deg=90
        ),
        "east": make_wall(
            model, body_context, storey, "Wall_East",
            length=ROOM_LENGTH + WALL_THICKNESS,
            position=[ROOM_WIDTH + half_t, -half_t, 0.0], rotation_deg=90
        ),
    }
    return walls


def create_room(model, body_context, storey):
    """
    PART 3: Build the IfcSpace (room) representing the enclosed area
    inside the 4 walls, and give it an explicit, reliable
    NetFloorArea quantity (Qto_SpaceBaseQuantities).

    NOTE: unlike IfcWall (a physical element -> spatial.assign_container),
    IfcSpace is itself a SPATIAL structure element, so it is linked to
    the storey via aggregate.assign_object (same relation type used for
    Project->Site->Building->Storey).
    """
    space = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSpace", name="Room_101")

    representation = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=ROOM_WIDTH, height=0.01, thickness=ROOM_LENGTH
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=space, representation=representation)

    # Position matches the interior bounds established by the walls in Part 2
    half_t = WALL_THICKNESS / 2
    matrix = np.eye(4)
    matrix[:3, 3] = [-half_t, half_t, 0.0]
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=space, matrix=matrix)

    ifcopenshell.api.run("aggregate.assign_object", model, products=[space], relating_object=storey)

    # Explicit, reliable quantity (this is what our extraction script will read later)
    qty_set = ifcopenshell.api.run("pset.add_qto", model, product=space, name="Qto_SpaceBaseQuantities")
    ifcopenshell.api.run(
        "pset.edit_qto", model, qto=qty_set,
        properties={"NetFloorArea": ROOM_WIDTH * ROOM_LENGTH}
    )

    return space


def create_window_in_wall(model, body_context, storey, host_wall):
    """
    PART 4 + 5: Cut an IfcOpeningElement into host_wall, then create an
    IfcWindow that fills that opening. This is the standard IFC pattern:

        IfcWall --[IfcRelVoidsElement]--> IfcOpeningElement
                                                |
                                     [IfcRelFillsElement]
                                                v
                                            IfcWindow

    This explicit opening (missing entirely in the Revit export we
    investigated earlier) is what makes sill-height extraction reliable.

    The opening/window is centered along Wall_South's length and placed
    at world Z = SILL_HEIGHT, cutting through the full wall thickness.
    """
    half_t = WALL_THICKNESS / 2
    wall_length = ROOM_WIDTH + WALL_THICKNESS
    opening_x = -half_t + (wall_length - WINDOW_WIDTH) / 2

    # --- PART 4: the opening ---
    opening = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcOpeningElement", name="Opening_1")
    opening_rep = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=WINDOW_WIDTH, height=WINDOW_HEIGHT, thickness=WALL_THICKNESS
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=opening, representation=opening_rep)

    matrix = np.eye(4)
    matrix[:3, 3] = [opening_x, -half_t, SILL_HEIGHT]
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=opening, matrix=matrix)

    ifcopenshell.api.run("feature.add_feature", model, feature=opening, element=host_wall)

    # --- PART 5: the window filling the opening ---
    window = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWindow", name="Window_1")
    window_rep = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=WINDOW_WIDTH, height=WINDOW_HEIGHT, thickness=WALL_THICKNESS
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=window, representation=window_rep)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=window, matrix=matrix)

    ifcopenshell.api.run("spatial.assign_container", model, products=[window], relating_structure=storey)
    ifcopenshell.api.run("feature.add_filling", model, opening=opening, element=window)

    # Explicit, reliable window quantities (Width / Height / Area)
    qty_set = ifcopenshell.api.run("pset.add_qto", model, product=window, name="Qto_WindowBaseQuantities")
    ifcopenshell.api.run(
        "pset.edit_qto", model, qto=qty_set,
        properties={"Width": WINDOW_WIDTH, "Height": WINDOW_HEIGHT, "Area": WINDOW_WIDTH * WINDOW_HEIGHT}
    )

    return opening, window


if __name__ == "__main__":
    model, project, site, building, storey = create_skeleton()
    body_context = create_geometric_contexts(model)
    walls = create_walls(model, body_context, storey)
    room = create_room(model, body_context, storey)
    opening, window = create_window_in_wall(model, body_context, storey, walls["south"])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model.write(OUTPUT_PATH)

    print(f"[OK] Model written to {OUTPUT_PATH}")
    print(f"  Project : {project.Name}")
    print(f"  Site    : {site.Name}")
    print(f"  Building: {building.Name}")
    print(f"  Storey  : {storey.Name}")
    print(f"  Walls   : {list(walls.keys())} ({len(model.by_type('IfcWall'))} total)")
    print(f"  Room    : {room.Name} (NetFloorArea = {ROOM_WIDTH * ROOM_LENGTH} m^2)")
    print(f"  Window  : {window.Name} ({WINDOW_WIDTH}m x {WINDOW_HEIGHT}m = {WINDOW_WIDTH * WINDOW_HEIGHT} m^2, sill={SILL_HEIGHT}m)")
    print(f"  Opening : {opening.Name} (voids {walls['south'].Name}, filled by {window.Name})")