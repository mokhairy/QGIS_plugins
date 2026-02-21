def classFactory(iface):
    from .plugin import SeismicProjectDbPlugin

    return SeismicProjectDbPlugin(iface)
