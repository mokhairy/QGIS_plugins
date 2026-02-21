# ============================================================
#  Export Birba/SPS and Birba/ShapeFiles groups to GeoPackages
#  Keeps styles, labels, symbology, colors
#  Author: Hussein Al Shibli | BGP Oman APC
# ============================================================

from qgis.core import (
    QgsProject,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsLayerTreeLayer,
    QgsLayerTreeGroup,
    QgsMapLayerStyle,
    QgsVectorLayer
)
import os

# ------------ PATHS TO YOUR GPKGs ---------------------------
BASE = r"E:/25 BIRBA/01-DataBase/GeoPackage"

SPS_GPKG    = os.path.join(BASE, "SPS.gpkg")
SURVEY_GPKG = os.path.join(BASE, "Survey.gpkg")

PARENT_GROUP_NAME = "Birba"   # top group in your screenshot

CHILD_GROUP_TO_GPKG = {
    "SPS":        SPS_GPKG,
    "ShapeFiles": SURVEY_GPKG,
}
# ------------------------------------------------------------

project = QgsProject.instance()
root = project.layerTreeRoot()
transform_context = project.transformContext()

print("\n===== START EXPORTING TO GEOPACKAGE (under 'Birba') =====\n")

# Find the Birba group at top level
parent_group = root.findGroup(PARENT_GROUP_NAME)
if parent_group is None:
    print(f"❌ Parent group '{PARENT_GROUP_NAME}' not found. Check the name.")
else:
    for child_name, gpkg_path in CHILD_GROUP_TO_GPKG.items():

        # Find child group (SPS / ShapeFiles) under Birba
        child_group = parent_group.findGroup(child_name)

        if child_group is None:
            print(f"❌ Group '{child_name}' under '{PARENT_GROUP_NAME}' not found. Skipping.\n")
            continue

        print(f"--- Exporting group '{PARENT_GROUP_NAME}/{child_name}' → {gpkg_path} ---")

        # Ensure folder exists
        gpkg_dir = os.path.dirname(gpkg_path)
        if not os.path.exists(gpkg_dir):
            os.makedirs(gpkg_dir)

        # Collect layer nodes
        nodes = [n for n in child_group.children() if isinstance(n, QgsLayerTreeLayer)]
        print(f"Found {len(nodes)} layers.\n")

        for idx, node in enumerate(nodes):
            layer = node.layer()
            if not layer:
                continue

            if layer.type() != layer.VectorLayer:
                print(f"[{idx+1}/{len(nodes)}] {layer.name()} → SKIPPED (not vector)")
                continue

            layer_name = layer.name()
            print(f"[{idx+1}/{len(nodes)}] {layer_name} ... ", end="")

            # Save style
            style = QgsMapLayerStyle()
            style.readFromLayer(layer)

            # Export into gpkg
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

            writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                transform_context,
                options
            )

            # Handle return formats
            if isinstance(writer_result, tuple):
                if len(writer_result) == 3:
                    res, err, new_file = writer_result
                elif len(writer_result) == 2:
                    res, new_file = writer_result
                    err = ""
                else:
                    res, err = writer_result[0], ""
            else:
                res, err = writer_result, ""

            if res != QgsVectorFileWriter.NoError:
                print(f"FAILED (code={res}, msg='{err}')")
                continue

            # Load new layer
            uri = f"{gpkg_path}|layername={layer_name}"
            new_layer = QgsVectorLayer(uri, layer_name, "ogr")

            if not new_layer.isValid():
                print("FAILED (invalid new layer)")
                continue

            # Apply style
            style.writeToLayer(new_layer)

            # Replace old layer in same position
            parent = node.parent()
            pos = parent.children().index(node)
            parent.insertLayer(pos, new_layer)
            parent.removeChildNode(node)

            print("OK")

        print(f"\n--- Finished group '{PARENT_GROUP_NAME}/{child_name}' ---\n")

print("\n✅ ALL DONE.")
print("   Birba/SPS        → SPS.gpkg")
print("   Birba/ShapeFiles → Survey.gpkg")
print("   Styles preserved.")
print("   | Hussein Al Shibli | BGP Oman APC\n")
