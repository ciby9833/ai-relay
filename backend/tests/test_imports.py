"""每个模块都要能导入：服务的入口模块（长连接、worker）没有测试覆盖时，导入错误会让服务启动即崩溃。"""
import importlib
import pkgutil

import app


def test_every_module_imports():
    failures = []
    for module in pkgutil.walk_packages(app.__path__, "app."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{module.name}: {exc!r}")
    assert not failures, "\n".join(failures)
