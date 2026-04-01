import importlib.util
import subprocess
import sys

from plugin import *


REQUIRED_PACKAGES = [
    ("cloudscraper", "cloudscraper"),
    ("beautifulsoup4", "bs4"),
    ("requests-cache", "requests_cache"),
    ("lxml", "lxml"),
]


def _ensure_requirements():
    missing = [package for package, module_name in REQUIRED_PACKAGES if importlib.util.find_spec(module_name) is None]
    if not missing:
        return

    if getattr(P, "logger", None) is not None:
        P.logger.info("Installing missing packages: %s", ", ".join(missing))

    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


setting = {
    "filepath": __file__,
    "use_db": True,
    "use_default_setting": True,
    "home_module": "category",
    "menu": {
        "uri": __package__,
        "name": "linkkf",
        "list": [
            {"uri": "setting", "name": "설정"},
            {"uri": "request", "name": "요청"},
            {"uri": "category", "name": "카테고리"},
            {"uri": "queue", "name": "대기열"},
            {"uri": "list", "name": "목록"},
            {"uri": "log", "name": "로그"},
        ],
    },
    "setting_menu": None,
    "default_route": "single",
}


P = create_plugin_instance(setting)
_ensure_requirements()

try:
    from .mod_basic import ModuleBasic

    P.set_module_list([ModuleBasic])
except Exception as e:
    P.logger.error(f"Exception:{str(e)}")
    P.logger.error(traceback.format_exc())
