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

# ------------ PATH TO YOUR SPS GPKG -------------------------
BASE_DIR  = r"E:/26 JAZAL/01-DataBase/GeoPackage"
SPS_GPKG  = os.path.join(BASE_DIR, "SPS.gpkg")

PARENT_GROUP_NAME = "Jazal"   # top group
SPS_GROUP_NAME    = "SPS"     # child group under Birba
# ------------------------------------------------------------

project = QgsProject.instance()
root = project.layerTreeRoot()
transform_context = project.transformContext()

print("\n===== START EXPORTING BIRBA/SPS TO SPS.gpkg =====\n")

# Find Birba group
birba_group = root.findGroup(PARENT_GROUP_NAME)
if birba_group is None:
    print(f"❌ Parent group '{PARENT_GROUP_NAME}' not found. Check the name.")
else:
    # Find SPS group inside Birba
    sps_group = birba_group.findGroup(SPS_GROUP_NAME)

    if sps_group is None:
        print(f"❌ Group '{SPS_GROUP_NAME}' under '{PARENT_GROUP_NAME}' not found.")
    else:
        # Ensure folder exists
        gpkg_dir = os.path.dirname(SPS_GPKG)
        if not os.path.exists(gpkg_dir):
            os.makedirs(gpkg_dir)

        # Get ALL descendant layer nodes under SPS (includes TO_VCU, Design SPS)
        nodes = list(sps_group.findLayers())
        print(f"Found {len(nodes)} layers under '{PARENT_GROUP_NAME}/{SPS_GROUP_NAME}'.\n")
        
        for idx, tree_layer in enumerate(nodes):
            layer = tree_layer.layer()
            if not layer:
                continue

            if layer.type() != layer.VectorLayer:
                print(f"[{idx+1}/{len(nodes)}] {layer.name()} → SKIPPED (not vector)")
                continue

            layer_name = layer.name()
            print(f"[{idx+1}/{len(nodes)}] {layer_name} ... ", end="")

            # Save current style
            style = QgsMapLayerStyle()
            style.readFromLayer(layer)

            # Export into SPS.gpkg
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

            writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                SPS_GPKG,
                transform_context,
                options
            )

            # Handle different return formats
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

            # Load new GPKG layer
            uri = f"{SPS_GPKG}|layername={layer_name}"
            new_layer = QgsVectorLayer(uri, layer_name, "ogr")

            if not new_layer.isValid():
                print("FAILED (invalid new layer)")
                continue

            # Reapply style
            style.writeToLayer(new_layer)

            # Replace the old layer in same position
            parent = tree_layer.parent()
            pos = parent.children().index(tree_layer)
            parent.insertLayer(pos, new_layer)
            parent.removeChildNode(tree_layer)

            print("OK")

        print(f"\n--- Finished exporting Birba/{SPS_GROUP_NAME} ---\n")

print("\n✅ ALL DONE.")
print(f"   Jazal/{SPS_GROUP_NAME} → {SPS_GPKG}")
print("   Styles preserved.")
print("   | Hussein Al Shibli | BGP Oman APC\n")
