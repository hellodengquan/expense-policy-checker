from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional


class DataLoadError(Exception):
    """数据加载异常基类"""
    pass


class CorruptedFileError(DataLoadError):
    """文件内容损坏异常"""
    pass


_LOCKS: Dict[Path, threading.Lock] = {}
_LOCKS_GLOBAL = threading.Lock()


def _get_file_lock(path: Path) -> threading.Lock:
    """获取或创建文件级别的线程锁"""
    with _LOCKS_GLOBAL:
        if path not in _LOCKS:
            _LOCKS[path] = threading.Lock()
        return _LOCKS[path]


@contextmanager
def file_lock_context(path: Path, exclusive: bool = True, timeout: float = 10.0):
    """
    文件级锁上下文管理器（线程锁+文件锁双重保护）
    - 线程锁：保护同进程多线程
    - fcntl.flock：保护跨进程并发
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_suffix(path.suffix + ".lock")
    thread_lock = _get_file_lock(path)

    acquired = thread_lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(f"获取线程锁超时: {path}")

    fh = None
    try:
        fh = open(lock_file, "a+")
        fcntl.flock(
            fh.fileno(),
            fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
        )
        yield fh
    finally:
        if fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            fh.close()
        thread_lock.release()


def load_json(
    path: Path,
    default: Optional[Any] = None,
    auto_create: bool = True,
    on_corrupt: str = "raise",
) -> Any:
    """
    加载 JSON 文件，支持多种容错策略

    参数:
        path: 目标文件路径
        default: 文件不存在时返回的默认值（auto_create=True 时写入该值）
        auto_create: 文件不存在时是否自动创建
        on_corrupt: 文件损坏时处理策略:
            - "raise": 抛出 CorruptedFileError
            - "fallback": 返回 default（若 default 为 None 则使用空列表/字典）
            - "backup": 备份损坏文件后创建新 default

    返回:
        解析后的 JSON 数据
    """
    path = Path(path)

    if not path.exists():
        if auto_create:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = default if default is not None else {}
            with file_lock_context(path, exclusive=True):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            return data
        return default if default is not None else {}

    with file_lock_context(path, exclusive=False):
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                parsed = default if default is not None else {}
            else:
                parsed = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            if on_corrupt == "raise":
                raise CorruptedFileError(
                    f"JSON 文件损坏，无法解析: {path}，原因: {e}"
                ) from e

            if on_corrupt == "backup":
                backup = path.with_suffix(path.suffix + f".corrupt.{os.getpid()}.bak")
                try:
                    path.rename(backup)
                except Exception:
                    pass

            parsed = default if default is not None else {}
            if on_corrupt in ("fallback", "backup") and auto_create:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(parsed, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
        return parsed


def save_json(path: Path, data: Any, indent: int = 2) -> None:
    """安全写入 JSON（含锁保护+原子替换）"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")

    with file_lock_context(path, exclusive=True):
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise


def load_yaml(
    path: Path,
    default: Optional[Any] = None,
    on_corrupt: str = "raise",
) -> Any:
    """加载 YAML 文件（容错策略同 load_json）"""
    try:
        import yaml
    except ImportError as e:
        raise ImportError("需要安装 PyYAML: pip install PyYAML") from e

    path = Path(path)
    if not path.exists():
        return default if default is not None else {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return default if default is not None else {}
        return yaml.safe_load(content) or (default if default is not None else {})
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as e:
        if on_corrupt == "raise":
            raise CorruptedFileError(
                f"YAML 文件损坏: {path}，原因: {e}"
            ) from e
        return default if default is not None else {}
