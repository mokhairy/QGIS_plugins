##Boundary/Points=group
##Build Boundary (Polygon + Line)=name

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsWkbTypes,
    QgsProcessingException,
    QgsFeatureSink,
    QgsCoordinateTransformContext,
    QgsVectorFileWriter
)
import processing


class BoundaryFromPoints(QgsProcessingAlgorithm):
    """
    Build a single boundary (polygon + line) from a points layer.
    Handles multipoint → singleparts automatically.
    Lets you choose convex hull (fast) or concave hull (tighter wrap).
    """

    # Parameter keys
    INPUT = "INPUT"
    GROUP_FIELD = "GROUP_FIELD"
    USE_CONCAVE = "USE_CONCAVE"
    CONCAVE_ALPHA = "CONCAVE_ALPHA"
    OUTPUT_POLY = "OUTPUT_POLY"
    OUTPUT_LINE = "OUTPUT_LINE"

    def initAlgorithm(self, config=None):
        # Input points layer
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                "Points layer",
                types=[QgsProcessing.TypeVectorPoint],
            )
        )

        # Optional group field (creates per-group boundaries if set)
        self.addParameter(
            QgsProcessingParameterField(
                self.GROUP_FIELD,
                "Group field (optional, leave empty for ONE boundary)",
                parentLayerParameterName=self.INPUT,
                type=QgsProcessingParameterField.Any,
                optional=True
            )
        )

        # Use concave?
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.USE_CONCAVE,
                "Use Concave Hull (tighter). If off: Convex Hull (fast/robust).",
                defaultValue=False
            )
        )

        # Concave alpha (only used when concave is on)
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CONCAVE_ALPHA,
                "Concave alpha (lower = tighter; suggested 0.3–0.8)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
                minValue=0.01,
                maxValue=9999.0
            )
        )

        # Outputs
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_POLY,
                "Boundary polygon"
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LINE,
                "Boundary line"
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        points = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        if points is None:
            raise QgsProcessingException("Points layer is required.")

        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        use_concave = self.parameterAsBool(parameters, self.USE_CONCAVE, context)
        alpha = self.parameterAsDouble(parameters, self.CONCAVE_ALPHA, context)

        # 0) Sanity check: must be point geometry
        if QgsWkbTypes.geometryType(points.wkbType()) != QgsWkbTypes.PointGeometry:
            raise QgsProcessingException("Input must be a point layer.")

        # 1) Ensure single-part points (avoid the 'single feature' hull error)
        needs_explode = QgsWkbTypes.isMultiType(points.wkbType()) or points.featureCount() <= 1
        if needs_explode:
            feedback.pushInfo("Exploding multipoint/single-feature layer to singlepoints…")
            points_single = processing.run(
                "native:multiparttosingleparts",
                {"INPUT": points, "OUTPUT": "memory:"},
                context=context, feedback=feedback, is_child_algorithm=True
            )["OUTPUT"]
        else:
            points_single = points

        # 2) Build boundary polygon (concave or convex)
        if use_concave:
            feedback.pushInfo(f"Building Concave Hull (alpha={alpha})…")
            hull_res = processing.run(
                "qgis:concavehull",
                {
                    "INPUT": points_single,
                    "ALPHA": float(alpha),
                    "FIELD": group_field if group_field else None,
                    "HOLES": False,
                    "NO_MULTIGEOMETRY": True
                },
                context=context, feedback=feedback, is_child_algorithm=True
            )
            poly_layer = hull_res["OUTPUT"]
        else:
            feedback.pushInfo("Building Convex Hull…")
            hull_res = processing.run(
                "native:convexhull",
                {
                    "INPUT": points_single,
                    "FIELD": group_field if group_field else None,
                    "OUTPUT": "memory:"
                },
                context=context, feedback=feedback, is_child_algorithm=True
            )
            poly_layer = hull_res["OUTPUT"]

        # If user asked for ONE boundary and group_field created many, dissolve them
        if not group_field:
            # Ensure truly one boundary polygon
            feedback.pushInfo("Dissolving to a single polygon boundary…")
            poly_layer = processing.run(
                "native:dissolve",
                {"INPUT": poly_layer, "OUTPUT": "memory:"},
                context=context, feedback=feedback, is_child_algorithm=True
            )["OUTPUT"]

        # 3) Convert polygon(s) to a line boundary
        feedback.pushInfo("Converting polygon to boundary line…")
        line_layer = processing.run(
            "native:polygonstolines",
            {"INPUT": poly_layer, "OUTPUT": "memory:"},
            context=context, feedback=feedback, is_child_algorithm=True
        )["OUTPUT"]

        # 4) Send to sinks
        (poly_sink, poly_dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT_POLY, context,
            poly_layer.fields(), poly_layer.wkbType(), poly_layer.sourceCrs()
        )
        (line_sink, line_dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT_LINE, context,
            line_layer.fields(), line_layer.wkbType(), line_layer.sourceCrs()
        )

        # Copy features to sinks
        for f in poly_layer.getFeatures():
            poly_sink.addFeature(f, QgsFeatureSink.FastInsert)
        for f in line_layer.getFeatures():
            line_sink.addFeature(f, QgsFeatureSink.FastInsert)

        feedback.pushInfo("Done. Added boundary polygon and line.")

        return {
            self.OUTPUT_POLY: poly_dest_id,
            self.OUTPUT_LINE: line_dest_id
        }

    def name(self):
        return "build_boundary_polygon_and_line"

    def displayName(self):
        return "Build Boundary (Polygon + Line)"

    def group(self):
        return "Points"

    def groupId(self):
        return "points"

    def createInstance(self):
        return BoundaryFromPoints()


# Register and run inside the Script runner
alg = BoundaryFromPoints()
