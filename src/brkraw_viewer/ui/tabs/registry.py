from .viewer import TITLE as VIEWER, build as build_viewer
from .params import TITLE as PARAMS, build as build_params
from .convert import TITLE as CONVERT, build as build_convert
from .config import TITLE as CONFIG, build as build_config
from .addons import TITLE as ADDONS, build as build_addons
from .extensions import TITLE as EXTENSIONS, build as build_extensions

def iter_tabs():
    return [
        (VIEWER, build_viewer),
        (ADDONS, build_addons),
        (PARAMS, build_params),
        (CONVERT, build_convert),
        (EXTENSIONS, build_extensions),
        (CONFIG, build_config),
    ]
