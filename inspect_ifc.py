"""
inspect_ifc.py
===============
General-purpose IFC inspection tool. Run this BEFORE writing/trusting
any extraction logic against a new or unfamiliar IFC file.

It answers: "what does this file actually contain?" -- schema version,
element counts, spatial hierarchy, and which Psets/Qtos exist on the
elements we care about (Space, Window, Wall) -- without assuming any
names in advance.

Usage:
    python inspect_ifc.py <path_to_ifc_file>
"""

import sys
import ifcopenshell


def print_header(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def inspect_schema(model):
    print_header("SCHEMA")
    print(f"  IFC Schema version: {model.schema}")


def inspect_element_counts(model):
    print_header("ELEMENT COUNTS")
    types_of_interest = [
        "IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey",
        "IfcSpace", "IfcWall", "IfcWindow", "IfcOpeningElement", "IfcDoor",
    ]
    for t in types_of_interest:
        count = len(model.by_type(t))
        print(f"  {t:.<30} {count}")


def inspect_hierarchy(model):
    print_header("SPATIAL HIERARCHY")

    def walk(entity, depth=0):
        print("  " + "  " * depth + f"- {entity.is_a()}: {entity.Name}")
        # IfcRelAggregates: spatial parent -> spatial children (Site/Building/Storey/Space)
        for rel in getattr(entity, "IsDecomposedBy", []):
            for child in rel.RelatedObjects:
                walk(child, depth + 1)
        # IfcRelContainedInSpatialStructure: physical elements hosted in a storey (Wall/Window)
        for rel in getattr(entity, "ContainsElements", []):
            for elem in rel.RelatedElements:
                print("  " + "  " * (depth + 1) + f"- {elem.is_a()}: {elem.Name}")

    project = model.by_type("IfcProject")
    if project:
        walk(project[0])


def inspect_property_sets(model, ifc_class):
    print_header(f"PROPERTY/QUANTITY SETS ON {ifc_class}")
    elements = model.by_type(ifc_class)
    if not elements:
        print(f"  (none found)")
        return
    for element in elements:
        print(f"  {element.Name} ({element.GlobalId}):")
        rels = getattr(element, "IsDefinedBy", [])
        if not rels:
            print("    (no property/quantity sets attached)")
        for rel in rels:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset_or_qto = rel.RelatingPropertyDefinition
            print(f"    - {pset_or_qto.Name} [{pset_or_qto.is_a()}]")
            if pset_or_qto.is_a("IfcElementQuantity"):
                for q in pset_or_qto.Quantities:
                    val = getattr(q, "LengthValue", None) or getattr(q, "AreaValue", None)
                    print(f"        {q.Name} = {val}")
            elif pset_or_qto.is_a("IfcPropertySet"):
                for p in pset_or_qto.HasProperties:
                    val = getattr(p, "NominalValue", None)
                    print(f"        {p.Name} = {val.wrappedValue if val else None}")


def inspect_relationships(model):
    print_header("OPENING / WINDOW RELATIONSHIPS")
    voids = model.by_type("IfcRelVoidsElement")
    fills = model.by_type("IfcRelFillsElement")
    if not voids:
        print("  [WARNING] No IfcRelVoidsElement found -- no wall has a proper opening cut.")
    for rel in voids:
        print(f"  {rel.RelatingBuildingElement.Name} --VOIDS--> {rel.RelatedOpeningElement.Name}")
    if not fills:
        print("  [WARNING] No IfcRelFillsElement found -- no window is linked to an opening.")
    for rel in fills:
        print(f"  {rel.RelatingOpeningElement.Name} --FILLED BY--> {rel.RelatedBuildingElement.Name}")


def main(ifc_path):
    model = ifcopenshell.open(ifc_path)

    inspect_schema(model)
    inspect_element_counts(model)
    inspect_hierarchy(model)
    inspect_property_sets(model, "IfcSpace")
    inspect_property_sets(model, "IfcWindow")
    inspect_relationships(model)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inspect_ifc.py <path_to_ifc_file>")
        sys.exit(1)
    main(sys.argv[1])