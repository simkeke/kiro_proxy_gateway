"""
通道模块自动导入

自动扫描 channels/ 下所有子包，触发元类自动注册。
新增渠道只需在 channels/ 下新建子包，无需修改任何导入代码。
"""

import importlib
import pkgutil
from pathlib import Path


def _auto_import() -> None:
    """扫描 channels/ 下所有子模块，触发元类注册"""
    package_dir = Path(__file__).parent
    package_name = __name__

    for info in pkgutil.walk_packages([str(package_dir)], prefix=package_name + "."):
        # 跳过 registry，避免循环导入
        if "registry" in info.name:
            continue
        try:
            importlib.import_module(info.name)
        except Exception:
            pass


_auto_import()
