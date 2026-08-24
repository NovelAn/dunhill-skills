"""加载 data-import 项目的全部 mission targets，供映射一致性测试使用。"""

import sys
from pathlib import Path

DATA_IMPORT_DIR = Path("/Users/novel/Projects/data-import")


def load_all_missions() -> list:
    """加载 data-import 项目全部 mission Task 对象。"""
    src = str(DATA_IMPORT_DIR / "src" / "data_pipeline")
    package_root = str(DATA_IMPORT_DIR / "src")
    sys.path.insert(0, str(DATA_IMPORT_DIR))  # config.missions
    sys.path.insert(0, src)  # modules.*
    sys.path.insert(0, package_root)  # data_pipeline.*
    try:
        from config.missions import Queue  # noqa: PLC0415
        from importlib import import_module  # noqa: PLC0415

        missions = []
        for module_path in Queue:
            missions.extend(getattr(import_module(module_path), "Missions"))
        return missions
    finally:
        for path in (str(DATA_IMPORT_DIR), src, package_root):
            if path in sys.path:
                sys.path.remove(path)


def mission_targets() -> set[str]:
    src = str(DATA_IMPORT_DIR / "src" / "data_pipeline")
    package_root = str(DATA_IMPORT_DIR / "src")
    sys.path.insert(0, str(DATA_IMPORT_DIR))  # config.missions
    sys.path.insert(0, src)  # modules.*
    sys.path.insert(0, package_root)  # data_pipeline.*
    try:
        from config.missions import Queue  # noqa: PLC0415
        from importlib import import_module  # noqa: PLC0415

        targets: set[str] = set()
        for module_path in Queue:
            targets.update(task.target for task in getattr(import_module(module_path), "Missions"))
        return targets
    finally:
        for path in (str(DATA_IMPORT_DIR), src, package_root):
            if path in sys.path:
                sys.path.remove(path)


if __name__ == "__main__":
    print(f"{len(mission_targets())} mission targets loaded")
