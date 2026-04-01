import importlib.util
import os
import subprocess
import sys
import yaml

from framework import F
from plugin import *


REQUIRED_PACKAGES = [
    ("cloudscraper", "cloudscraper"),
    ("beautifulsoup4", "bs4"),
    ("requests-cache", "requests_cache"),
    ("lxml", "lxml"),
]


def _get_runtime_package_name():
    return (__package__ or "").split(".")[0] or os.path.basename(os.path.dirname(__file__))


def _get_declared_package_name():
    info_path = os.path.join(os.path.dirname(__file__), "info.yaml")
    try:
        with open(info_path, encoding="utf-8") as file:
            info = yaml.safe_load(file) or {}
        package_name = str(info.get("package_name", "")).strip()
        if package_name != "":
            return package_name
    except Exception:
        pass
    return os.path.basename(os.path.dirname(__file__))


def ensure_sqlalchemy_bind(package_name=None):
    package_name = package_name or _get_declared_package_name()
    try:
        if getattr(F, "app", None) is None:
            return package_name
        binds = F.app.config.setdefault("SQLALCHEMY_BINDS", {})
        if package_name not in binds:
            db_path = os.path.join(F.config["path_data"], "db", f"{package_name}.db")
            binds[package_name] = f"sqlite:///{db_path}?check_same_thread=False"
    except Exception:
        pass
    return package_name


def ensure_sqlalchemy_binds():
    names = []
    for candidate in [_get_declared_package_name(), _get_runtime_package_name()]:
        candidate = str(candidate or "").strip()
        if candidate != "" and candidate not in names:
            names.append(candidate)
    for name in names:
        ensure_sqlalchemy_bind(name)
    return names


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

ensure_sqlalchemy_binds()
P = create_plugin_instance(setting)
ensure_sqlalchemy_binds()
ensure_sqlalchemy_bind(P.package_name)
_ensure_requirements()

try:
    from .mod_basic import ModuleBasic

    P.set_module_list([ModuleBasic])
except Exception as e:
    P.logger.error(f"Exception:{str(e)}")
    P.logger.error(traceback.format_exc())
