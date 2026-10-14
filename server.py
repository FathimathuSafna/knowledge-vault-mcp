"""
Shim for backward compatibility. All core functionality lives in `knowledge_vault.server`.
"""
import sys
from pathlib import Path

src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

import knowledge_vault.server as _server_module
from knowledge_vault.server import *  # noqa: F401, F403


class _ModuleProxy(sys.modules[__name__].__class__):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if hasattr(_server_module, name):
            setattr(_server_module, name, value)


sys.modules[__name__].__class__ = _ModuleProxy

if __name__ == "__main__":
    _server_module.main()