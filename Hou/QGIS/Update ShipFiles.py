
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
import re
import json
import time

# ------------------- SIGNATURE -------------------
SIGNATURE_TEXT = "Hussein Al Shibli | BGP Oman APC"

# ------------------- CONFIG ----------------------

# Root folder that contains ALL shapefile subfolders
SHAPEFILES_DIR = r"E:/25 BIRBA/04-Shape file/From Survey/Block C"   # <-- adjust if needed

# GeoPackage output
BASE = r"E:/25 BIRBA/01-DataBase/GeoPackage"
SURVEY_GPKG = os.path.join(BASE, "Survey.gpkg")

# State file (to remember last imported timestamps)
STATE_FILE = SURVEY_GPKG + ".import_state.json"

# QGIS group structure
PARENT_GROUP_NAME = "Birba"
CHILD_GROUP_NAME = "ShapeFiles"

# Behavior switches
LOAD_INTO_QGIS = True                    # Add/replace layers into QGIS
MIRROR_FOLDER_GROUPS_IN_QGIS = True      # Create subgroups matching folders
APPLY_QML_IF_FOUND = True                # Apply .qml style if exists next to shapefile
COPY_STYLE_FROM_EXISTING_LAYER = True    # Copy style from existing project layer (same generated name)

# Layer naming rule inside GPKG:
USE_RELATIVE_FOLDER_IN_LAYER_NAME = True

# Separator used when building GPKG layer names from folders
PATH_SEP = "__"

# Sidecar files to consider when detecting changes
SHAPEFILE_SIDE_EXTS = [".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx"]

# -------------------------------------------------


def safe_layer_name(name: str) -> str:
    name = name.replace("\\", "_").replace("/", "_").replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_\-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def list_shapefiles_recursive(root_folder: str):
    shp_files = []
    if not os.path.isdir(root_folder):
        return shp_files

    for r, _, files in os.walk(root_folder):
        for f in files:
            if f.lower().endswith(".shp"):
                shp_files.append(os.path.join(r, f))

    shp_files.sort(key=lambda p: p.lower())
    return shp_files


def ensure_group_path(root_group: QgsLayerTreeGroup, parts):
    g = root_group
    for name in parts:
        existing = g.findGroup(name)
        if existing is None:
            existing = g.addGroup(name)
        g = existing
    return g


def find_layer_node_in_group(group: QgsLayerTreeGroup, layer_name: str):
    for child in group.children():
        if isinstance(child, QgsLayerTreeLayer):
            lyr = child.layer()
            if lyr and lyr.name() == layer_name:
                return child
    return None


def capture_style_from_project(layer_name: str):
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr and lyr.name() == layer_name:
            st = QgsMapLayerStyle()
            st.readFromLayer(lyr)
            return st
    return None


def apply_qml_if_exists(layer: QgsVectorLayer, shp_path: str):
    qml = os.path.splitext(shp_path)[0] + ".qml"
    if os.path.exists(qml):
        layer.loadNamedStyle(qml)
        layer.triggerRepaint()


def export_shp_to_gpkg(shp_path: str, gpkg_path: str, layer_name: str, transform_context):
    src = QgsVectorLayer(shp_path, layer_name, "ogr")
    if not src.isValid():
        return False, f"Invalid shapefile: {shp_path}"

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

    res = QgsVectorFileWriter.writeAsVectorFormatV3(
        src, gpkg_path, transform_context, opts
    )

    res_code = res[0] if isinstance(res, tuple) else res
    if res_code != QgsVectorFileWriter.NoError:
        return False, f"Write failed (code={res_code})"

    return True, ""


def load_gpkg_layer(gpkg_path: str, layer_name: str):
    uri = f"{gpkg_path}|layername={layer_name}"
    lyr = QgsVectorLayer(uri, layer_name, "ogr")
    return lyr if lyr.isValid() else None


def build_layer_name(shp_path: str, root_folder: str):
    file_base = os.path.splitext(os.path.basename(shp_path))[0]

    if not USE_RELATIVE_FOLDER_IN_LAYER_NAME:
        return safe_layer_name(file_base)

    rel_dir = os.path.relpath(os.path.dirname(shp_path), root_folder)
    if rel_dir in (".", "", None):
        combined = file_base
    else:
        rel_dir_norm = rel_dir.replace("\\", "/").strip("/")
        rel_dir_norm = rel_dir_norm.replace("/", PATH_SEP)
        combined = f"{rel_dir_norm}{PATH_SEP}{file_base}"

    return safe_layer_name(combined)


def latest_mtime_for_shapefile(shp_path: str) -> float:
    """
    Return the latest modified time among .shp and sidecar files (if exist).
    This gives a reliable "did anything change?" detector.
    """
    base = os.path.splitext(shp_path)[0]
    mtimes = []

    for ext in SHAPEFILE_SIDE_EXTS:
        p = base + ext
        if os.path.exists(p):
            try:
                mtimes.append(os.path.getmtime(p))
            except Exception:
                pass

    # If somehow nothing found, fallback to shp itself
    if not mtimes:
        try:
            return os.path.getmtime(shp_path)
        except Exception:
            return 0.0

    return max(mtimes)


def load_state(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_state(path: str, state: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Could not save state file: {path} ({e})")


def main():
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    transform_context = project.transformContext()

    print("\n===== SMART SHAPEFILES → SURVEY.GPKG (ONLY NEW/CHANGED) =====")
    print(f"Root folder: {SHAPEFILES_DIR}")
    print(f"Target GPKG: {SURVEY_GPKG}")
    print(f"State file : {STATE_FILE}")
    print(f"Signature : {SIGNATURE_TEXT}\n")

    if not os.path.exists(BASE):
        os.makedirs(BASE)

    state = load_state(STATE_FILE)
    shp_files = list_shapefiles_recursive(SHAPEFILES_DIR)

    print(f"Found {len(shp_files)} shapefiles (recursive).")
    print(f"Known in state: {len(state)} layers.\n")

    if LOAD_INTO_QGIS:
        parent = root.findGroup(PARENT_GROUP_NAME)
        if parent is None:
            parent = root.addGroup(PARENT_GROUP_NAME)

        top_group = parent.findGroup(CHILD_GROUP_NAME)
        if top_group is None:
            top_group = parent.addGroup(CHILD_GROUP_NAME)
    else:
        top_group = None

    imported_new = 0
    updated = 0
    skipped = 0
    failed = 0

    for i, shp in enumerate(shp_files, start=1):
        layer_name = build_layer_name(shp, SHAPEFILES_DIR)

        rel_dir = os.path.relpath(os.path.dirname(shp), SHAPEFILES_DIR)
        rel_dir_norm = rel_dir.replace("\\", "/").strip("/")

        current_mtime = latest_mtime_for_shapefile(shp)
        prev_mtime = float(state.get(layer_name, 0.0))

        is_new = (layer_name not in state)
        is_changed = (current_mtime > prev_mtime + 0.0001)  # small tolerance

        if is_new:
            action = "NEW"
        elif is_changed:
            action = "UPDATE"
        else:
            action = "SKIP"

        print(f"[{i}/{len(shp_files)}] {layer_name} → {action} ... ", end="")

        if action == "SKIP":
            skipped += 1
            print("OK (unchanged)")
            continue

        saved_style = None
        if COPY_STYLE_FROM_EXISTING_LAYER:
            saved_style = capture_style_from_project(layer_name)

        ok, msg = export_shp_to_gpkg(shp, SURVEY_GPKG, layer_name, transform_context)
        if not ok:
            failed += 1
            print(f"FAILED ({msg})")
            continue

        new_layer = load_gpkg_layer(SURVEY_GPKG, layer_name)
        if not new_layer:
            failed += 1
            print("FAILED (load error)")
            continue

        if saved_style:
            saved_style.writeToLayer(new_layer)
        elif APPLY_QML_IF_FOUND:
            apply_qml_if_exists(new_layer, shp)

        if LOAD_INTO_QGIS and top_group is not None:
            target_group = top_group

            if MIRROR_FOLDER_GROUPS_IN_QGIS and rel_dir_norm not in (".", "", None):
                parts = [p for p in rel_dir_norm.split("/") if p.strip()]
                target_group = ensure_group_path(top_group, parts)

            existing_node = find_layer_node_in_group(target_group, layer_name)
            if existing_node:
                parent_node = existing_node.parent()
                pos = parent_node.children().index(existing_node)
                parent_node.insertLayer(pos, new_layer)
                parent_node.removeChildNode(existing_node)
            else:
                target_group.addLayer(new_layer)

            project.addMapLayer(new_layer, False)

        # Update state
        state[layer_name] = current_mtime

        if action == "NEW":
            imported_new += 1
        else:
            updated += 1

        print("OK")

    save_state(STATE_FILE, state)

    print("\n✅ ALL DONE.")
    print(f"New imported : {imported_new}")
    print(f"Updated      : {updated}")
    print(f"Skipped      : {skipped}")
    print(f"Failed       : {failed}")
    print("- Only NEW or CHANGED shapefiles were written to the GeoPackage.")
    print(f"| {SIGNATURE_TEXT}\n")


# ---------------- RUN ----------------
main()

# Hussein Al Shibli | BGP Oman APC
