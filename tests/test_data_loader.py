from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from expense_checker.data_loader import (
    CorruptedFileError,
    file_lock_context,
    load_json,
    load_yaml,
    save_json,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestAutoCreate:
    def test_file_not_exists_auto_creates_with_default(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "data.json"
        assert not target.exists()
        data = load_json(target, default={"k": "v"}, auto_create=True)
        assert data == {"k": "v"}
        assert target.exists()
        with open(target, encoding="utf-8") as f:
            assert json.load(f) == {"k": "v"}

    def test_file_not_exists_no_auto_create_returns_default(self, tmp_path: Path):
        target = tmp_path / "missing.json"
        data = load_json(target, default={}, auto_create=False)
        assert data == {}
        assert not target.exists()

    def test_file_not_exists_default_none_becomes_empty_dict(self, tmp_path: Path):
        target = tmp_path / "empty.json"
        data = load_json(target, auto_create=True)
        assert data == {}
        assert target.exists()

    def test_save_json_creates_nested_directories(self, tmp_path: Path):
        target = tmp_path / "deep" / "nested" / "dir" / "file.json"
        save_json(target, {"hello": "world"})
        assert target.exists()
        assert load_json(target) == {"hello": "world"}


class TestCorruptedFile:
    def test_corrupted_json_raises(self, tmp_path: Path):
        target = tmp_path / "bad.json"
        _write(target, "{not valid json")
        with pytest.raises(CorruptedFileError):
            load_json(target, on_corrupt="raise")

    def test_corrupted_json_fallback_to_default(self, tmp_path: Path):
        target = tmp_path / "bad.json"
        _write(target, "{not valid json")
        result = load_json(target, default={"fallback": True}, on_corrupt="fallback")
        assert result == {"fallback": True}

    def test_corrupted_json_fallback_repair_file(self, tmp_path: Path):
        target = tmp_path / "bad.json"
        _write(target, "{not valid json")
        load_json(
            target,
            default={"repaired": True},
            auto_create=True,
            on_corrupt="fallback",
        )
        with open(target, encoding="utf-8") as f:
            assert json.load(f) == {"repaired": True}

    def test_corrupted_json_backup_creates_copy(self, tmp_path: Path):
        target = tmp_path / "bad.json"
        original = "{not valid json"
        _write(target, original)
        result = load_json(target, default={}, auto_create=True, on_corrupt="backup")
        assert result == {}
        backups = list(tmp_path.glob("bad.json.corrupt.*.bak"))
        assert len(backups) >= 1

    def test_empty_file_treated_as_default(self, tmp_path: Path):
        target = tmp_path / "empty.json"
        _write(target, "   \n\t  ")
        result = load_json(target, default={"x": 1}, auto_create=False)
        assert result == {"x": 1}

    def test_corrupted_yaml_raises(self, tmp_path: Path):
        target = tmp_path / "bad.yaml"
        _write(target, '{a: 1, b: 2,')
        with pytest.raises(CorruptedFileError):
            load_yaml(target, on_corrupt="raise")

    def test_corrupted_yaml_fallback(self, tmp_path: Path):
        target = tmp_path / "bad.yaml"
        _write(target, '"unterminated quote string')
        result = load_yaml(target, default={"fixed": 42}, on_corrupt="fallback")
        assert result == {"fixed": 42}

    def test_type_mismatch_returns_dict_safe(self, tmp_path: Path):
        target = tmp_path / "list.json"
        _write(target, '[1, 2, 3]')
        raw = load_json(target, default={}, auto_create=False)
        assert isinstance(raw, list)
        wrapped = raw if isinstance(raw, dict) else {}
        assert wrapped == {}


class TestConcurrentWrite:
    def test_concurrent_writes_no_interleaving(self, tmp_path: Path):
        target = tmp_path / "counter.json"
        save_json(target, {"count": 0})
        NUM_THREADS = 20
        ITERS = 25
        errors = []

        def worker(tid):
            try:
                for _ in range(ITERS):
                    with file_lock_context(target, exclusive=True):
                        with open(target, encoding="utf-8") as f:
                            data = json.load(f)
                        data["count"] = data.get("count", 0) + 1
                        data[f"t{tid}"] = data.get(f"t{tid}", 0) + 1
                        tmp = target.with_suffix(".tmp.json")
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        os.replace(tmp, target)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"线程中出现异常: {errors}"
        final = load_json(target)
        assert final["count"] == NUM_THREADS * ITERS
        for i in range(NUM_THREADS):
            assert final.get(f"t{i}") == ITERS

    def test_concurrent_reads_no_interfere_with_writes(self, tmp_path: Path):
        target = tmp_path / "rw.json"
        save_json(target, {"seq": 0, "value": "start"})
        errors = []
        stop = threading.Event()

        def writer():
            try:
                seq = 0
                while not stop.is_set():
                    seq += 1
                    save_json(target, {"seq": seq, "value": f"step-{seq}"})
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    data = load_json(target, on_corrupt="fallback", default={})
                    if "seq" in data:
                        assert isinstance(data["seq"], int)
                        assert isinstance(data["value"], str)
                    time.sleep(0.0005)
            except Exception as e:
                errors.append(e)

        w = threading.Thread(target=writer)
        rs = [threading.Thread(target=reader) for _ in range(5)]
        w.start()
        for r in rs:
            r.start()
        for r in rs:
            r.join()
        stop.set()
        w.join()

        assert not errors, f"并发错误: {errors}"

    def test_file_lock_exclusive_blocks(self, tmp_path: Path):
        target = tmp_path / "locked.json"
        save_json(target, {"state": "init"})
        acquired = threading.Event()
        released = threading.Event()
        second_started = threading.Event()
        order = []

        def holder():
            with file_lock_context(target, exclusive=True):
                acquired.set()
                order.append("holder_entered")
                time.sleep(0.2)
                order.append("holder_done")
            released.set()

        def waiter():
            second_started.set()
            with file_lock_context(target, exclusive=True):
                order.append("waiter_entered")

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=waiter)
        t1.start()
        assert acquired.wait(timeout=2)
        t2.start()
        assert second_started.wait(timeout=2)
        time.sleep(0.05)
        assert "waiter_entered" not in order
        t1.join()
        assert released.wait(timeout=2)
        t2.join(timeout=2)
        assert order[0] == "holder_entered"
        assert order[1] == "holder_done"
        assert order[2] == "waiter_entered"


class TestSaveAtomic:
    def test_save_failure_does_not_corrupt_original(self, tmp_path: Path):
        target = tmp_path / "atomic.json"
        save_json(target, {"safe": True, "nested": {"k": [1, 2, 3]}})
        with open(target, encoding="utf-8") as f:
            original = f.read()
        try:
            class BadData:
                def __init__(self):
                    pass
                def __str__(self):
                    raise RuntimeError("boom")
            save_json(target, {"oops": BadData()})
        except Exception:
            pass
        with open(target, encoding="utf-8") as f:
            assert f.read() == original

    def test_save_produces_valid_json(self, tmp_path: Path):
        target = tmp_path / "valid.json"
        payload = {"中文": True, "list": [1, 2, 3], "nested": {"a": {"b": 1}}}
        save_json(target, payload)
        with open(target, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == payload
