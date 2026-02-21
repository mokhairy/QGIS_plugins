"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
import os

# Import your algorithm classes
from .package_layers_algorithm import MultipleLayersToKmzAlgorithm
# from .geotagged_images_algorithm import GeotaggedImagesToKmzAlgorithm
from .image_layer_to_kmz_algorithm import LayerToKmzWithPhotosAlgorithm

plugin_dir = os.path.dirname(__file__)

class KmzToolsProvider(QgsProcessingProvider):

    def unload(self):
        QgsProcessingProvider.unload(self)
    
    def __init__(self):
        super().__init__()
    
    def id(self):
        return 'kmz_tools'
    
    def name(self):
        return 'KMZ Tools'
    
    def longName(self):
        return 'Custom KMZ/KML Processing Tools'
    
    def icon(self):
        icon_path = os.path.join(plugin_dir, 'logo.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        else:
            return QIcon()
    
    def initGui(self):
        pass
    
    def loadAlgorithms(self):
        self.addAlgorithm(MultipleLayersToKmzAlgorithm())
        # self.addAlgorithm(GeotaggedImagesToKmzAlgorithm())
        self.addAlgorithm(LayerToKmzWithPhotosAlgorithm())
    
    def supportedOutputRasterLayerExtensions(self):
        return ['kmz', 'kml']