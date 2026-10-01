import importlib
import pkgutil

# modules installed explicitly (route-prepended to override base handlers), not auto-mounted
_OVERRIDES = {"live_modes"}

routers = []
for _m in pkgutil.iter_modules(__path__):
    if _m.name in _OVERRIDES:
        continue
    _mod = importlib.import_module(f"{__name__}.{_m.name}")
    if hasattr(_mod, "router"):
        routers.append(_mod.router)
