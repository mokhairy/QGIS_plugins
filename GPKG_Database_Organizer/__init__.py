def classFactory(iface):
    from .plugin import GpkgDatabaseOrganizerPlugin

    return GpkgDatabaseOrganizerPlugin(iface)
