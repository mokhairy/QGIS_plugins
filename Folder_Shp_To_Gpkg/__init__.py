def classFactory(iface):
    from .plugin import FolderShpToGpkgPlugin

    return FolderShpToGpkgPlugin(iface)
