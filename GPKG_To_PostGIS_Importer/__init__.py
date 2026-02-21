def classFactory(iface):
    from .plugin import GpkgToPostgisImporterPlugin

    return GpkgToPostgisImporterPlugin(iface)
