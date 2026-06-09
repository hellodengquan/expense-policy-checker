from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

ContentProbe = Optional[Callable[[str], bool]]


class DataLoadError(Exception):
    """数据加载异常基类"""
    pass


class CorruptedFileError(DataLoadError):
    """文件内容损坏异常"""
    pass


class EncodingDetectionError(DataLoadError):
    """文件编码无法识别"""
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


def _detect_encoding(raw: bytes, fallback: str = "utf-8") -> Tuple[str, bool]:
    """
    尝试检测字节串编码。
    返回 (encoding, used_chardet_flag)
    """
    # 1) 先试 BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", False
    if raw.startswith(b"\xff\xfe\x00\x00") or raw.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32", False
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16", False

    # 2) 试 chardet（若可用）
    try:
        import chardet  # type: ignore
    except ImportError:
        chardet = None  # type: ignore

    if chardet is not None:
        result = chardet.detect(raw)
        detected = result.get("encoding")
        confidence = result.get("confidence") or 0.0
        language = (result.get("language") or "").lower()
        # 中文 GB 家族（GB2312/GBK/GB18030）置信度阈值放宽到 0.35
        threshold = 0.35 if language == "zh" else 0.5
        if detected and confidence >= threshold:
            # chardet 有时对 utf-8 检测为 ascii，修正
            if detected.lower() == "ascii":
                return "utf-8", True
            # GB2312/CP936/GB18030 统一用 GBK（GBK 是超集，能处理更多字符）
            if detected.lower() in ("gb2312", "gbk", "cp936", "gb18030"):
                return "gbk", True
            return detected, True

    return fallback, False


def _has_high_bytes(raw: bytes) -> bool:
    """判断 bytes 中是否含有大于 0x7F 的字节（非 ASCII）"""
    return any(b > 0x7F for b in raw)


def _probe_passes(content: str, probe: ContentProbe) -> bool:
    """执行语义探测，True 表示探测通过"""
    if probe is None:
        return True
    try:
        return bool(probe(content))
    except Exception:
        return False


def _read_text_safely(
    path: Path,
    content_probe: ContentProbe = None,
) -> Tuple[str, str]:
    """
    多层级编码容错的文件读取，支持语义探测以避免乱码文本被当成合法内容返回。

    策略顺序（解码成功 + 语义探测通过 才返回）：
    1. BOM 识别（UTF-8 BOM / UTF-16 / UTF-32）
    2. 默认 UTF-8 严格读取（占绝大多数的场景）
    3. 若含非 ASCII 字节，暴力尝试常见中文/东亚编码：GBK、Big5、Shift_JIS、EUC-KR
    4. chardet 自动检测（若可用）
    5. 终极降级：UTF-8 errors=replace（此步不做语义探测，硬兜底）

    参数:
        path: 文件路径
        content_probe: 回调(content:str)->bool，True 表示内容合法；None 表示不探测

    返回: (text_content, encoding_used)
    """
    path = Path(path)

    # 统一读取 bytes（避免多次 I/O）
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise CorruptedFileError(f"无法读取文件 {path}: {e}") from e

    if not raw:
        return "", "utf-8"

    def _ok(text: str) -> bool:
        return _probe_passes(text, content_probe)

    # 1) BOM 快速识别
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            decoded = raw.decode("utf-8-sig")
            if _ok(decoded):
                return decoded, "utf-8-sig"
        except UnicodeDecodeError:
            pass
    if raw.startswith(b"\xff\xfe\x00\x00") or raw.startswith(b"\x00\x00\xfe\xff"):
        try:
            decoded = raw.decode("utf-32")
            if _ok(decoded):
                return decoded, "utf-32"
        except UnicodeDecodeError:
            pass
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            decoded = raw.decode("utf-16")
            if _ok(decoded):
                return decoded, "utf-16"
        except UnicodeDecodeError:
            pass

    # 2) 严格 UTF-8
    try:
        decoded = raw.decode("utf-8")
        if _ok(decoded):
            return decoded, "utf-8"
    except UnicodeDecodeError:
        pass

    has_non_ascii = _has_high_bytes(raw)

    # 3) 含非 ASCII 时暴力尝试常见东亚编码
    if has_non_ascii:
        for enc in ("gbk", "big5", "shift_jis", "euc-kr"):
            try:
                decoded = raw.decode(enc)
                if _ok(decoded):
                    return decoded, enc
            except (UnicodeDecodeError, LookupError):
                continue

    # 4) chardet 自动检测（含语言放宽策略）
    try:
        import chardet  # type: ignore
    except ImportError:
        chardet = None  # type: ignore

    if chardet is not None:
        result = chardet.detect(raw)
        detected = result.get("encoding")
        confidence = result.get("confidence") or 0.0
        language = (result.get("language") or "").lower()
        threshold = 0.35 if language == "zh" else 0.5
        if detected and confidence >= threshold:
            if detected.lower() == "ascii":
                detected = "utf-8"
            if detected.lower() in ("gb2312", "gbk", "cp936", "gb18030"):
                detected = "gbk"
            try:
                decoded = raw.decode(detected)
                if _ok(decoded):
                    return decoded, detected
            except (UnicodeDecodeError, LookupError):
                pass

    # 5) 终极降级：errors=replace（不做语义探测，保证返回字符串）
    try:
        return raw.decode("utf-8", errors="replace"), "utf-8(replace)"
    except Exception as e:
        raise EncodingDetectionError(
            f"无法用任何编码读取文件 {path}: {e}"
        ) from e


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
            content, _enc = _read_text_safely(
                path, content_probe=lambda c: bool(json.loads(c) is not None)
            )
            if not content.strip():
                parsed = default if default is not None else {}
            else:
                parsed = json.loads(content)
        except (json.JSONDecodeError, EncodingDetectionError, OSError) as e:
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
        def _yaml_dict_probe(content: str) -> bool:
            parsed = yaml.safe_load(content)
            return isinstance(parsed, dict)
        content, _enc = _read_text_safely(path, content_probe=_yaml_dict_probe)
        if not content.strip():
            return default if default is not None else {}
        loaded = yaml.safe_load(content)
        if not isinstance(loaded, dict):
            # 标量 / 列表型 YAML：视为损坏（收窄到 dict 政策文件）
            if on_corrupt == "raise":
                raise CorruptedFileError(
                    f"YAML 文件根节点必须是 dict，实际为 {type(loaded).__name__}"
                )
            return default if default is not None else {}
        return loaded
    except (yaml.YAMLError, EncodingDetectionError, OSError) as e:
        if on_corrupt == "raise":
            raise CorruptedFileError(
                f"YAML 文件损坏: {path}，原因: {e}"
            ) from e
        return default if default is not None else {}
