# ============================================================
#  Auto-Import SHAPEFILES → Survey GeoPackage (GPKG)
#  Uses SHAPEFILE FILE NAME as layer name
#  Overwrites existing layers, adds new ones automatically
#  No SPS logic included
#
#  Author: Hussein Al Shibli | BGP Oman APC
# ============================================================

from qgis.core import (
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsLayerTreeLayer,
    QgsLayerTreeGroup,
    QgsMapLayerStyle,
)
import os

# ------------------- SIGNATURE -------------------
SIGNATURE_TEXT = "Hussein Al Shibli | BGP Oman APC"

# ------------------- CONFIG ----------------------

# Folder containing UPDATED & NEW shapefiles
SHAPEFILES_DIR = r"E:/26 JAZAL/04-Shape file/From PDO"   # <-- adjust if needed

# GeoPackage output
BASE = r"E:/26 JAZAL/01-DataBase/GeoPackage"
SURVEY_GPKG = os.path.join(BASE, "Survey.gpkg")

# QGIS group structure
PARENT_GROUP_NAME = "Jazal"
CHILD_GROUP_NAME = "Survey"

# Behavior switches
RECURSIVE_SCAN = False          # True = scan subfolders
LOAD_INTO_QGIS = True           # Auto-load / replace layers in QGIS
APPLY_QML_IF_FOUND = True       # Apply .qml if exists next to shapefile
COPY_STYLE_FROM_EXISTING_LAYER = True  # Copy style from existing QGIS layer

# -------------------------------------------------


def list_shapefiles(folder, recursive=False):
    shp_files = []
    if not os.path.isdir(folder):
        return shp_files

    if recursive:
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".shp"):
                    shp_files.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            if f.lower().endswith(".shp"):
                shp_files.append(os.path.join(folder, f))

    shp_files.sort(key=lambda p: os.path.basename(p).lower())
    return shp_files


def ensure_group(root, parent_name, child_name):
    parent = root.findGroup(parent_name)
    if parent is None:
        parent = root.addGroup(parent_name)

    child = parent.findGroup(child_name)
    if child is None:
        child = parent.addGroup(child_name)

    return child


def find_layer_in_group(group, layer_name):
    for child in group.children():
        if isinstance(child, QgsLayerTreeLayer):
            lyr = child.layer()
            if lyr and lyr.name() == layer_name:
                return child
    return None


def capture_style_from_project(layer_name):
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.name() == layer_name:
            st = QgsMapLayerStyle()
            st.readFromLayer(lyr)
            return st
    return None


def apply_qml_if_exists(layer, shp_path):
    qml = os.path.splitext(shp_path)[0] + ".qml"
    if os.path.exists(qml):
        layer.loadNamedStyle(qml)
        layer.triggerRepaint()


def export_shp_to_gpkg(shp_path, gpkg_path, layer_name, transform_context):
    src = QgsVectorLayer(shp_path, layer_name, "ogr")
    if not src.isValid():
        return False, "Invalid shapefile"

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

    res = QgsVectorFileWriter.writeAsVectorFormatV3(
        src, gpkg_path, transform_context, opts
    )

    if isinstance(res, tuple):
        res = res[0]

    return res == QgsVectorFileWriter.NoError, ""


def load_gpkg_layer(gpkg_path, layer_name):
    uri = f"{gpkg_path}|layername={layer_name}"
    lyr = QgsVectorLayer(uri, layer_name, "ogr")
    return lyr if lyr.isValid() else None


def main():
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    transform_context = project.transformContext()

    print("\n===== SHAPEFILES → SURVEY.GPKG (AUTO UPDATE) =====")
    print(f"Signature: {SIGNATURE_TEXT}\n")

    if not os.path.exists(BASE):
        os.makedirs(BASE)

    shp_files = list_shapefiles(SHAPEFILES_DIR, RECURSIVE_SCAN)
    print(f"Found {len(shp_files)} shapefiles.\n")

    if LOAD_INTO_QGIS:
        qgis_group = ensure_group(root, PARENT_GROUP_NAME, CHILD_GROUP_NAME)
    else:
        qgis_group = None

    for i, shp in enumerate(shp_files, start=1):
        layer_name = os.path.splitext(os.path.basename(shp))[0]
        print(f"[{i}/{len(shp_files)}] {layer_name} ... ", end="")

        saved_style = None
        if COPY_STYLE_FROM_EXISTING_LAYER:
            saved_style = capture_style_from_project(layer_name)

        ok, msg = export_shp_to_gpkg(shp, SURVEY_GPKG, layer_name, transform_context)
        if not ok:
            print("FAILED")
            continue

        new_layer = load_gpkg_layer(SURVEY_GPKG, layer_name)
        if not new_layer:
            print("FAILED (load error)")
            continue

        if saved_style:
            saved_style.writeToLayer(new_layer)
        elif APPLY_QML_IF_FOUND:
            apply_qml_if_exists(new_layer, shp)

        if LOAD_INTO_QGIS and qgis_group:
            old_node = find_layer_in_group(qgis_group, layer_name)
            if old_node:
                parent = old_node.parent()
                pos = parent.children().index(old_node)
                parent.insertLayer(pos, new_layer)
                parent.removeChildNode(old_node)
            else:
                qgis_group.addLayer(new_layer)

            project.addMapLayer(new_layer, False)

        print("OK")

    print("\n✅ ALL DONE.")
    print("Survey GeoPackage updated.")
    print(f"| {SIGNATURE_TEXT}\n")


# ---------------- RUN ----------------
main()

# Hussein Al Shibli | BGP Oman APC
