"""
generate_ifc.py
================
Generates a small IFC4 model: 1 building, 1 storey, 1 enclosed room
(IfcSpace), 4 walls, 1 window installed via a proper IfcOpeningElement.

Now PARAMETERIZED so the same script produces all 3 required test
fixtures (compliant / violation / missing-data) by passing different
CLI arguments -- no code duplication, no separate scripts per scenario.

Usage examples:
    # Compliant model (defaults satisfy all 3 rules)
    python generate_ifc.py --output data/generated/compliant_model.ifc

    # Violation model: room area below 12 m^2 (rule 1 fails)
    python generate_ifc.py --room-width 3.0 --room-length 3.0 \
        --output data/generated/violation_model.ifc

    # Missing-data model: window with no opening relationship and no
    # quantities at all (simulates the exact Revit export failure mode)
    python generate_ifc.py --missing-data \
        --output data/generated/missing_data_model.ifc
"""

import argparse
import os

import ifcopenshell
import ifcopenshell.api
import numpy as np

# ---- Default dimensions (produce the original compliant model) ----
DEFAULT_ROOM_WIDTH = 4.0
DEFAULT_ROOM_LENGTH = 3.5
DEFAULT_WALL_HEIGHT = 3.0
DEFAULT_WALL_THICKNESS = 0.2
DEFAULT_WINDOW_WIDTH = 1.5
DEFAULT_WINDOW_HEIGHT = 1.2
DEFAULT_SILL_HEIGHT = 0.9


def create_skeleton():
    """PART 1: Project -> Site -> Building -> Storey, SI units in metres."""
    model = ifcopenshell.file(schema="IFC4")

    project = ifcopenshell.api.run(
        "root.create_entity", model,
        ifc_class="IfcProject", name="IFC Compliance Checker - Sample Project"
    )
    ifcopenshell.api.run("unit.assign_unit", model, length={"is_metric": True, "raw": "METERS"})

    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Sample Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name="Sample Building")
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Ground Floor")

    ifcopenshell.api.run("aggregate.assign_object", model, products=[site], relating_object=project)
    ifcopenshell.api.run("aggregate.assign_object", model, products=[building], relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", model, products=[storey], relating_object=building)

    return model, project, site, building, storey


def create_geometric_contexts(model):
    """Required once per model: 3D 'Model' context + 'Body' sub-context."""
    model3d = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run(
        "context.add_context", model,
        context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=model3d
    )
    return body


def make_wall(model, body_context, storey, name, length, height, thickness, position, rotation_deg):
    """Creates one IfcWall with a rectangular extrusion, placed/rotated in world space."""
    wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name=name)

    representation = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=length, height=height, thickness=thickness
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


def create_walls(model, body_context, storey, room_width, room_length, wall_height, wall_thickness):
    """PART 2: 4 walls forming a closed rectangle; interior = room_width x room_length."""
    half_t = wall_thickness / 2

    walls = {
        "south": make_wall(
            model, body_context, storey, "Wall_South",
            length=room_width + wall_thickness, height=wall_height, thickness=wall_thickness,
            position=[-half_t, -half_t, 0.0], rotation_deg=0
        ),
        "north": make_wall(
            model, body_context, storey, "Wall_North",
            length=room_width + wall_thickness, height=wall_height, thickness=wall_thickness,
            position=[-half_t, room_length + half_t, 0.0], rotation_deg=0
        ),
        "west": make_wall(
            model, body_context, storey, "Wall_West",
            length=room_length + wall_thickness, height=wall_height, thickness=wall_thickness,
            position=[-half_t, -half_t, 0.0], rotation_deg=90
        ),
        "east": make_wall(
            model, body_context, storey, "Wall_East",
            length=room_length + wall_thickness, height=wall_height, thickness=wall_thickness,
            position=[room_width + half_t, -half_t, 0.0], rotation_deg=90
        ),
    }
    return walls


def create_room(model, body_context, storey, room_width, room_length, wall_thickness):
    """PART 3: IfcSpace with explicit NetFloorArea quantity."""
    space = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSpace", name="Room_101")

    representation = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=room_width, height=0.01, thickness=room_length
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=space, representation=representation)

    half_t = wall_thickness / 2
    matrix = np.eye(4)
    matrix[:3, 3] = [-half_t, half_t, 0.0]
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=space, matrix=matrix)

    ifcopenshell.api.run("aggregate.assign_object", model, products=[space], relating_object=storey)

    qty_set = ifcopenshell.api.run("pset.add_qto", model, product=space, name="Qto_SpaceBaseQuantities")
    ifcopenshell.api.run(
        "pset.edit_qto", model, qto=qty_set,
        properties={"NetFloorArea": room_width * room_length}
    )

    return space


def create_window_in_wall(model, body_context, storey, host_wall, room_width, wall_thickness,
                           window_width, window_height, sill_height, missing_data=False):
    """
    PART 4 + 5: Cut an IfcOpeningElement into host_wall, then create an
    IfcWindow filling that opening.

    If missing_data=True, the window is created WITHOUT the opening
    relationship and WITHOUT explicit quantities -- reproducing the
    exact Revit-export failure mode (window placed with no
    IfcRelVoidsElement / IfcRelFillsElement at all), so extraction and
    validation can be tested against genuinely incomplete data.
    """
    half_t = wall_thickness / 2
    wall_length = room_width + wall_thickness
    win_x = -half_t + (wall_length - window_width) / 2

    matrix = np.eye(4)
    matrix[:3, 3] = [win_x, -half_t, sill_height]

    if missing_data:
        # Window exists and is placed, but with NO opening cut into the
        # wall, NO fill relationship, and NO quantity set -- everything
        # sill-height/area extraction depends on is absent by design.
        window = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWindow", name="Window_Orphan")
        window_rep = ifcopenshell.api.run(
            "geometry.add_wall_representation", model,
            context=body_context, length=window_width, height=window_height, thickness=wall_thickness
        )
        ifcopenshell.api.run("geometry.assign_representation", model, product=window, representation=window_rep)
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=window, matrix=matrix)
        ifcopenshell.api.run("spatial.assign_container", model, products=[window], relating_structure=storey)
        return None, window

    # --- PART 4: the opening ---
    opening = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcOpeningElement", name="Opening_1")
    opening_rep = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=window_width, height=window_height, thickness=wall_thickness
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=opening, representation=opening_rep)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=opening, matrix=matrix)
    ifcopenshell.api.run("feature.add_feature", model, feature=opening, element=host_wall)

    # --- PART 5: the window filling the opening ---
    window = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWindow", name="Window_1")
    window_rep = ifcopenshell.api.run(
        "geometry.add_wall_representation", model,
        context=body_context, length=window_width, height=window_height, thickness=wall_thickness
    )
    ifcopenshell.api.run("geometry.assign_representation", model, product=window, representation=window_rep)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=window, matrix=matrix)
    ifcopenshell.api.run("spatial.assign_container", model, products=[window], relating_structure=storey)
    ifcopenshell.api.run("feature.add_filling", model, opening=opening, element=window)

    qty_set = ifcopenshell.api.run("pset.add_qto", model, product=window, name="Qto_WindowBaseQuantities")
    ifcopenshell.api.run(
        "pset.edit_qto", model, qto=qty_set,
        properties={"Width": window_width, "Height": window_height, "Area": window_width * window_height}
    )

    return opening, window


def generate_model(
    output_path,
    room_width=DEFAULT_ROOM_WIDTH,
    room_length=DEFAULT_ROOM_LENGTH,
    wall_height=DEFAULT_WALL_HEIGHT,
    wall_thickness=DEFAULT_WALL_THICKNESS,
    window_width=DEFAULT_WINDOW_WIDTH,
    window_height=DEFAULT_WINDOW_HEIGHT,
    sill_height=DEFAULT_SILL_HEIGHT,
    missing_data=False,
):
    """
    Top-level entry point. Builds a full model with the given
    parameters and writes it to output_path. Returns a summary dict
    for logging/printing.
    """
    model, project, site, building, storey = create_skeleton()
    body_context = create_geometric_contexts(model)
    walls = create_walls(model, body_context, storey, room_width, room_length, wall_height, wall_thickness)
    room = create_room(model, body_context, storey, room_width, room_length, wall_thickness)
    opening, window = create_window_in_wall(
        model, body_context, storey, walls["south"], room_width, wall_thickness,
        window_width, window_height, sill_height, missing_data=missing_data
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    model.write(output_path)

    return {
        "output_path": output_path,
        "room_area_m2": room_width * room_length,
        "window_area_m2": window_width * window_height,
        "sill_height_m": None if missing_data else sill_height,
        "missing_data": missing_data,
        "wall_count": len(model.by_type("IfcWall")),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a parameterized IFC compliance-checker test model.")
    parser.add_argument("--output", default="data/generated/compliant_model.ifc", help="Output .ifc file path")
    parser.add_argument("--room-width", type=float, default=DEFAULT_ROOM_WIDTH)
    parser.add_argument("--room-length", type=float, default=DEFAULT_ROOM_LENGTH)
    parser.add_argument("--wall-height", type=float, default=DEFAULT_WALL_HEIGHT)
    parser.add_argument("--wall-thickness", type=float, default=DEFAULT_WALL_THICKNESS)
    parser.add_argument("--window-width", type=float, default=DEFAULT_WINDOW_WIDTH)
    parser.add_argument("--window-height", type=float, default=DEFAULT_WINDOW_HEIGHT)
    parser.add_argument("--sill-height", type=float, default=DEFAULT_SILL_HEIGHT)
    parser.add_argument(
        "--missing-data", action="store_true",
        help="Create a window with NO opening relationship and NO quantities (simulates incomplete IFC data)."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    summary = generate_model(
        output_path=args.output,
        room_width=args.room_width,
        room_length=args.room_length,
        wall_height=args.wall_height,
        wall_thickness=args.wall_thickness,
        window_width=args.window_width,
        window_height=args.window_height,
        sill_height=args.sill_height,
        missing_data=args.missing_data,
    )

    print(f"[OK] Model written to {summary['output_path']}")
    print(f"  Room area   : {summary['room_area_m2']} m^2")
    print(f"  Window area : {summary['window_area_m2']} m^2")
    print(f"  Sill height : {summary['sill_height_m']}")
    print(f"  Missing data mode : {summary['missing_data']}")
    print(f"  Walls       : {summary['wall_count']}")