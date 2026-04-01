from .setup import P


package_name = P.package_name
logger = P.logger
plugin_info = P.plugin_info


def _module():
    if P is None or P.module_list is None or len(P.module_list) == 0:
        return None
    return P.module_list[0]


def plugin_load():
    module = _module()
    if module is not None:
        module.plugin_load()


def plugin_unload():
    module = _module()
    if module is not None:
        module.plugin_unload()


def socketio_callback(cmd, data):
    module = _module()
    if module is not None and hasattr(module, "socketio_callback"):
        module.socketio_callback(cmd, data)


def socketio_list_refresh():
    module = _module()
    if module is not None and hasattr(module, "socketio_list_refresh"):
        module.socketio_list_refresh()

