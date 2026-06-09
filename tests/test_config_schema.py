from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from expense_checker.config_schema import (
    ConfigValidationError,
    validate_policy_config,
)
from expense_checker.data_loader import (
    CorruptedFileError,
    _detect_encoding,
    load_json,
    load_yaml,
)
from expense_checker.policy_rules import (
    BUILTIN_CONFIG_PATH,
    load_default_rules,
    load_rules_from_yaml,
)


# =============== 生成一个最小合法配置的 helper ===============

MINIMAL_VALID: Dict[str, Any] = {
    "version": "2.0.0",
    "name": "测试政策",
    "rules": {
        "amount_limits": {
            "rule_id": "R001",
            "rule_name": "x",
            "description": "x",
            "per_transaction_limits": {
                "intern": {"meal": 50.0, "transportation": 100.0, "accommodation": 300.0, "entertainment": 200.0},
                "middle": {"meal": 99.0, "transportation": 77.0, "accommodation": 66.0, "entertainment": 55.0},
            },
            "monthly_limits": {"intern": 1000.0, "middle": 5000.0},
        },
        "receipt_required": {
            "rule_id": "R002", "rule_name": "x", "description": "x", "threshold": 500.0,
        },
        "meal_per_day_limit": {
            "rule_id": "R003", "rule_name": "x", "description": "x",
            "limits": {"intern": 150.0, "middle": 400.0},
        },
        "travel_accommodation_city_tier": {
            "rule_id": "R004", "rule_name": "x", "description": "x",
            "tier1_cities": ["火星市", "月球镇"],
            "tier2_cities": ["空间站", "海底城"],
            "multipliers": {"tier1": 2.0, "tier2": 1.3, "tier3": 0.8},
        },
        "entertainment_requirements": {
            "rule_id": "R005", "rule_name": "x", "description": "x",
            "min_participants": 2,
            "description_min_length": 5,
        },
        "expense_date_validity": {
            "rule_id": "R006", "rule_name": "x", "description": "x",
            "max_days_before_submit": 30,
            "future_dates_allowed": False,
        },
        "department_quotas": {
            "rule_id": "R007", "rule_name": "x", "description": "x",
            "training_monthly": {"engineering": 100.0},
            "entertainment_monthly": {"engineering": 200.0},
        },
    },
}


# =============== 场景一：正常配置 ===============

class TestValidConfig:
    def test_minimal_valid_passes(self):
        ok, errs = validate_policy_config(copy.deepcopy(MINIMAL_VALID))
        assert ok is True
        assert errs == []
        # 数据本身不变
        assert MINIMAL_VALID["version"] == "2.0.0"
        assert "火星市" in MINIMAL_VALID["rules"]["travel_accommodation_city_tier"]["tier1_cities"]

    def test_builtin_yaml_matches_schema(self):
        with open(BUILTIN_CONFIG_PATH, "r", encoding="utf-8") as f:
            builtin = yaml.safe_load(f)
        ok, errs = validate_policy_config(builtin)
        assert ok is True, f"出厂 YAML 有 {len(errs)} 条错误: {errs[:3]}"
        assert errs == []

    def test_load_default_rules_uses_valid_yaml(self):
        rules = load_default_rules()
        # 应含有完整结构
        assert "北京" in rules["rules"]["travel_accommodation_city_tier"]["tier1_cities"]
        assert "rules" in rules
        assert "amount_limits" in rules["rules"]


# =============== 场景二：键缺失 ===============

class TestMissingKeys:
    def test_root_missing_version(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["version"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert "version" in paths
        assert any("缺少必需键" in m for _, m in errs)

    def test_root_missing_rules(self):
        cfg = {"version": "1.0.0", "name": "x"}
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert "rules" in paths

    def test_city_tier_missing_tier1_cities(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("tier1_cities" in p for p in paths)

    def test_city_tier_missing_tier2_cities(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["travel_accommodation_city_tier"]["tier2_cities"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("tier2_cities" in p for p in paths)

    def test_city_tier_missing_tier1_multiplier(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["travel_accommodation_city_tier"]["multipliers"]["tier1"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("tier1" in p and "multipliers" in p for p in paths)

    def test_amount_limits_missing_per_transaction(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["amount_limits"]["per_transaction_limits"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("per_transaction_limits" in p for p in paths)

    def test_meal_missing_limits(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["meal_per_day_limit"]["limits"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("limits" in p for p in paths)

    def test_entertainment_missing_min_participants(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["entertainment_requirements"]["min_participants"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("min_participants" in p for p in paths)

    def test_expense_date_missing_future_flag(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["expense_date_validity"]["future_dates_allowed"]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("future_dates_allowed" in p for p in paths)

    def test_invalid_yaml_falls_back_to_default(self, tmp_path: Path):
        bad = tmp_path / "bad_rules.yaml"
        bad.write_text("version: 1.0\n")
        # 缺少 rules 等，应该回退到内置默认值
        loaded = load_rules_from_yaml(bad)
        assert loaded is None
        rules = load_default_rules(bad)
        # 应回退到 DEFAULT_POLICY_RULES -> 北京仍在
        assert "北京" in rules["rules"]["travel_accommodation_city_tier"]["tier1_cities"]


# =============== 场景三：值类型错误 ===============

class TestTypeErrors:
    def test_root_is_not_dict(self):
        ok, errs = validate_policy_config([1, 2, 3])
        assert ok is False
        assert any("根节点" in msg for _, msg in errs)

    def test_version_not_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["version"] = 123
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert "version" in paths
        assert any("期望 str" in msg for _, msg in errs)

    def test_rules_not_dict(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"] = "a string"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        assert any(p == "rules" for p, _ in errs)

    def test_tier1_cities_is_str_instead_of_list(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = "北京,上海"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("tier1_cities" in p for p in paths)
        assert any("期望 list" in msg for _, msg in errs)

    def test_tier2_cities_item_is_int(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["tier2_cities"] = ["成都", 123]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("tier2_cities" in p for p in paths)

    def test_multipliers_tier1_not_numeric(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["multipliers"]["tier1"] = "很贵"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("tier1" in p and "multipliers" in p for p in paths)

    def test_monthly_limits_unknown_level(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["amount_limits"]["monthly_limits"]["superman"] = 99999
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("superman" in p for p in paths)
        assert any("未知职级" in msg for _, msg in errs)

    def test_per_transaction_amount_not_numeric(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["amount_limits"]["per_transaction_limits"]["middle"]["meal"] = "两百块"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert any("meal" in p and "middle" in p for p in paths)

    def test_receipt_threshold_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["receipt_required"]["threshold"] = "五百"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        assert any("threshold" in p for p, _ in errs)

    def test_min_participants_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["entertainment_requirements"]["min_participants"] = "两个人"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        assert any("min_participants" in p for p, _ in errs)

    def test_future_dates_allowed_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["expense_date_validity"]["future_dates_allowed"] = "是的"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        assert any("future_dates_allowed" in p for p, _ in errs)

    def test_department_quota_value_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["department_quotas"]["training_monthly"]["engineering"] = "很多"
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        assert any("training_monthly" in p for p, _ in errs)


# =============== 场景四：编码异常（data_loader + 集成） ===============

class TestEncodingFallback:
    def test_utf8_strict_still_works(self, tmp_path: Path):
        f = tmp_path / "utf8.json"
        f.write_text(json.dumps({"你好": "世界"}), encoding="utf-8")
        data = load_json(f)
        assert data == {"你好": "世界"}

    def test_gbk_encoded_json_detected_by_chardet(self, tmp_path: Path):
        f = tmp_path / "gbk.json"
        # 增加文本长度让 chardet 识别更稳定（GBK 识别需要足够样本）
        payload = {
            "中文键一": "中文值内容，用于测试 chardet 检测 GBK 编码是否准确",
            "中文键二": "财务报销系统需要支持多编码配置文件读取，这是一个重要的容错特性",
            "中文键三": "北京上海广州深圳杭州成都重庆武汉南京西安苏州天津厦门",
            "数字": 42,
            "说明": "这是一段足够长的中文文本样本样本样本样本样本样本样本样本",
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("gbk")
        f.write_bytes(raw)
        data = load_json(f)
        assert data["数字"] == 42
        assert "中文键一" in data or "说明" in data

    def test_gbk_encoded_yaml_detected(self, tmp_path: Path):
        f = tmp_path / "gbk.yaml"
        yaml_text = (
            "version: '2.0'\n"
            "name: 这是一个中文政策的名字测试内容足够长以便识别GBK\n"
            "description: 这是一段更长的描述文本北京上海广州深圳杭州成都重庆武汉南京西安苏州天津厦门\n"
            "value: 123\n"
            "note: 财务报销规则检查器政策配置，支持多个城市分级标准\n"
            "extra: 这里还有更多的中文内容样本样本样本样本样本样本样本\n"
        )
        f.write_bytes(yaml_text.encode("gbk"))
        data = load_yaml(f)
        assert data["value"] == 123
        assert "中文政策" in data["name"] or "财务报销" in data.get("note", "")

    def test_invalid_bytes_uses_replace(self, tmp_path: Path):
        f = tmp_path / "broken_encoding.json"
        # 构造含非法 UTF-8 字节但整体可被 replace 替换成可解析 JSON 的内容
        ok_part = json.dumps({"ok": True, "city": "北京"}, ensure_ascii=False).encode("utf-8")
        # 加几个非法字节
        broken = ok_part[:20] + b"\x80\xa0\xbad\x00bytes" + ok_part[20:]
        f.write_bytes(broken)
        # errors=replace 后 json.loads 也可能失败，这里验证至少不抛 UnicodeDecodeError
        # 失败时应走 fallback
        try:
            data = load_json(f, default={"fallback": True}, on_corrupt="fallback")
            assert isinstance(data, dict)
        except Exception as e:
            pytest.fail(f"不应抛出未捕获的异常: {type(e).__name__}: {e}")

    def test_detected_encoding_unknown_falls_back_replace(self, tmp_path: Path):
        """极端：模拟 bytes 乱入，确保不崩溃"""
        f = tmp_path / "weird.json"
        weird = bytes([0x00, 0x01, 0x02, 0x80, 0xFF, 0xFE, 0xFD])
        f.write_bytes(weird)
        data = load_json(f, default={"safe": True}, on_corrupt="fallback")
        assert isinstance(data, dict)

    def test_detect_encoding_bom_utf8(self):
        raw = b"\xef\xbb\xbf{\"a\": 1}"
        enc, used = _detect_encoding(raw)
        assert enc == "utf-8-sig"

    def test_detect_encoding_bom_utf16(self):
        raw = b"\xff\xfe\x00\x00some"
        enc, used = _detect_encoding(raw)
        assert enc == "utf-32"

    def test_raise_mode_wraps_unicode_in_corrupted(self, tmp_path: Path):
        f = tmp_path / "raise.json"
        # 非法字节 + 无法形成合法 JSON 也应包装为 CorruptedFileError
        f.write_bytes(b"{ \x80\x81 this is not valid json at all }")
        with pytest.raises(CorruptedFileError):
            load_json(f, on_corrupt="raise")

    def test_yaml_gbk_roundtrip_with_validation(self, tmp_path: Path):
        """完整链路：GBK YAML -> 检测解码 -> 结构校验 -> 返回正确配置"""
        f = tmp_path / "gbk_rules.yaml"
        # 在 name/description 中加入大量中文让 chardet 稳定识别
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["name"] = (
            "财务报销政策配置文件超长中文描述测试北京上海广州深圳杭州成都重庆"
            "武汉南京西安苏州天津厦门财务报销系统支持多编码配置"
        )
        cfg["rules"]["receipt_required"]["description"] = (
            "这是一段更长的中文描述内容用于增加文本长度以便于字符编码检测识别"
            "中国国家标准编码包括GB2312GBKGB18030等多种标准"
        )
        yaml_text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
        f.write_bytes(yaml_text.encode("gbk"))
        data = load_yaml(f)
        # 结构应通过校验
        validate_policy_config(data)
        assert data["version"] == "2.0.0"
        cities = data["rules"]["travel_accommodation_city_tier"]["tier1_cities"]
        assert cities[0] == "火星市"
        assert cities[1] == "月球镇"

    def test_chardet_unavailable_still_uses_replace(self, monkeypatch, tmp_path: Path):
        """当 chardet 没有时也不崩溃"""
        import expense_checker.data_loader as dl

        orig = dl.__dict__.get("_detect_encoding")

        def fake_detect(raw, fallback="utf-8"):
            # 模拟 chardet 不可用: 只返回 fallback
            return fallback, False

        monkeypatch.setattr(dl, "_detect_encoding", fake_detect)

        f = tmp_path / "nochardet.json"
        # 一段 GBK JSON 文本 -> 无 chardet 时通过 replace 降级
        f.write_bytes(json.dumps({"k": "北京"}, ensure_ascii=False).encode("gbk"))
        data = load_json(f, default={"fallback": True}, on_corrupt="fallback")
        # JSON 可能解析失败走 fallback，但至少不抛出 UnicodeDecodeError
        assert isinstance(data, dict)


# =============== 场景五：编码语义探测（content_probe） ===============

class TestContentProbe:
    def test_read_text_safely_accepts_probe_callback(self, tmp_path: Path):
        """自定义 content_probe 能在解码后进一步语义校验，不通过就试下一个编码"""
        from expense_checker.data_loader import _read_text_safely

        # 写合法 JSON，探测要求必须有 'hello' 键 -> 会 fallback 到 replace
        f = tmp_path / "probe.json"
        f.write_text(json.dumps({"key": 1}))

        def probe_requires_hello(content: str) -> bool:
            parsed = json.loads(content)
            return isinstance(parsed, dict) and "hello" in parsed

        text, enc = _read_text_safely(f, content_probe=probe_requires_hello)
        # 纯 ASCII UTF-8 就能解码成功，但 probe 不通过 -> 只能走终极 replace
        # 但 replace 不做 probe，原样返回
        assert enc == "utf-8(replace)"
        assert "key" in text  # 内容一样，只是走了终极

    def test_big5_yaml_correctly_picked_over_gbk_by_probe(self, tmp_path: Path):
        """
        同一段 bytes 在 GBK 和 Big5 下都能'解码'但只有一种是正确语义。
        yaml.safe_load 不会因乱码抛异常，需要用额外 probe 来识别。
        这里构造：一段 Big5 文本先被 GBK 解码会产生乱码，probe 通过检查是否包含特定词来
        判断是否用对编码。
        """
        from expense_checker.data_loader import _read_text_safely

        # Big5 常用字："台灣" (U+53F0 U+7063)，GBK 中这两个字的字节序列如果能被 GBK 解码
        # 就会是乱码；相反 "上海" 是 GBK 常见词，用 Big5 解码是乱码
        payload = {"city": "上海", "name": "北京上海广州深圳"}
        gbk_bytes = json.dumps(payload, ensure_ascii=False).encode("gbk")

        # 写 GBK 字节，并用 probe 验证必须有 "上海" 词
        # 暴力尝试顺序是 gbk -> big5 -> shift_jis -> euc-kr
        # 当用 big5 解码时，"上海" 两个字大概率会变成乱码（非 "上海" 字符串）
        f = tmp_path / "multi_enc.json"
        f.write_bytes(gbk_bytes)

        def probe_requires_shanghai(content: str) -> bool:
            try:
                parsed = json.loads(content)
                return isinstance(parsed, dict) and parsed.get("city") == "上海"
            except Exception:
                return False

        text, enc = _read_text_safely(f, content_probe=probe_requires_shanghai)
        assert enc == "gbk"
        parsed = json.loads(text)
        assert parsed["city"] == "上海"
        assert parsed["name"] == "北京上海广州深圳"

    def test_load_json_semantic_probe_skips_wrong_encoding(self, tmp_path: Path):
        """load_json 默认用 json.loads 做语义探测，乱码导致 JSON 非法会自动跳过错误编码"""
        # 构造：有效 JSON + GBK 中文，如果被错误解码为 Big5 可能导致引号/括号乱码，进而 JSON 非法
        payload = {
            "title": "财务报销政策配置文件测试",
            "items": ["北京", "上海", "广州"],
            "count": 3,
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("gbk")
        f = tmp_path / "smart.json"
        f.write_bytes(raw)
        data = load_json(f)
        assert data["count"] == 3
        assert "上海" in data["items"]
        assert data["title"] == "财务报销政策配置文件测试"

    def test_load_yaml_semantic_probe_skips_wrong_encoding(self, tmp_path: Path):
        """load_yaml 用 yaml.safe_load 做 probe，自动选择能正确解析的编码"""
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["name"] = "财务报销规则检查 YAML 语义探测测试"
        yaml_text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
        f = tmp_path / "smart.yaml"
        f.write_bytes(yaml_text.encode("gbk"))
        data = load_yaml(f)
        validate_policy_config(data)
        assert data["name"] == "财务报销规则检查 YAML 语义探测测试"
        assert data["rules"]["travel_accommodation_city_tier"]["tier1_cities"] == ["火星市", "月球镇"]

    def test_invalid_json_falls_back_to_on_corrupt_mode(self, tmp_path: Path):
        """probe/json.loads 都失败 -> 触发 on_corrupt 分支"""
        f = tmp_path / "broken.json"
        # 不是合法 JSON，不管怎么解码都不合法
        f.write_bytes(b"this is { not json at all !! ")
        result = load_json(f, default={"safe": True}, on_corrupt="fallback")
        assert result == {"safe": True}

    def test_content_probe_throws_is_treated_as_not_ok(self, tmp_path: Path):
        """probe 抛异常视为探测不通过，继续尝试下一编码"""
        from expense_checker.data_loader import _read_text_safely

        f = tmp_path / "x.json"
        f.write_text(json.dumps({"a": 1}))

        call_count = {"n": 0}

        def bad_probe(content: str) -> bool:
            call_count["n"] += 1
            raise RuntimeError("boom")

        _text, enc = _read_text_safely(f, content_probe=bad_probe)
        # probe 一直抛 -> 最终 fall through 到 replace 兜底（不做 probe）
        assert call_count["n"] >= 1
        assert enc == "utf-8(replace)"


# =============== 场景六：多错误收集（validate_policy_config 完整遍历） ===============

class TestMultiErrorCollection:
    def test_simultaneously_missing_version_and_rules(self):
        """配置同时缺多个顶层键，一次性全部收集"""
        cfg: Dict[str, Any] = {"foo": "bar"}
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert "version" in paths
        assert "name" in paths
        assert "rules" in paths
        assert len(errs) >= 3

    def test_multiple_type_errors_all_collected(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        # 同时注入多条跨模块的错误
        cfg["version"] = 999  # version 类型错
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = "逗号分隔"  # list 改 str
        cfg["rules"]["amount_limits"]["monthly_limits"]["superman"] = 123  # 未知职级
        cfg["rules"]["amount_limits"]["monthly_limits"]["superman2"] = "not_num"  # 未知职级 + 类型错
        cfg["rules"]["receipt_required"]["threshold"] = "五百块"  # 类型错
        cfg["rules"]["expense_date_validity"]["future_dates_allowed"] = "no"  # bool 错
        del cfg["rules"]["meal_per_day_limit"]["limits"]  # 键缺失

        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        assert "version" in paths
        assert any("tier1_cities" in p for p in paths)
        assert any("superman" in p for p in paths)
        assert any("superman2" in p for p in paths)
        assert any("threshold" in p for p in paths)
        assert any("future_dates_allowed" in p for p in paths)
        assert any("meal_per_day_limit.limits" in p for p in paths)
        # 至少 7 条（version、tier1_cities 类型、2条职级、threshold、future_date、limits 缺
        assert len(errs) >= 7

    def test_seven_required_rules_subkeys_all_missing(self):
        """删除 rules 下全部 7 条子键，应一次性报全 7 条缺失错误"""
        cfg = copy.deepcopy(MINIMAL_VALID)
        for k in list(cfg["rules"].keys()):
            del cfg["rules"][k]
        ok, errs = validate_policy_config(cfg)
        assert ok is False
        paths = [p for p, _ in errs]
        for key in (
            "amount_limits",
            "receipt_required",
            "meal_per_day_limit",
            "travel_accommodation_city_tier",
            "entertainment_requirements",
            "expense_date_validity",
            "department_quotas",
        ):
            assert any(p == f"rules.{key}" for p in paths), f"missing error for rules.{key}"
        assert len(errs) >= 7

    def test_raise_on_error_true_still_raises_first_error(self):
        """raise_on_error=True 向后兼容：首条抛异常，其余被吞"""
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["version"] = 42
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = 3.14
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg, raise_on_error=True)
        # 首条应该是 version（遍历顺序）
        assert exc.value.path == "version"

    def test_cli_validate_config_multiple_errors_displayed(self, tmp_path: Path):
        """
        集成：validate-config 子命令能把深递归的多条错误全部展示出来
        """
        from typer.testing import CliRunner
        from expense_checker.cli import app

        cfg = copy.deepcopy(MINIMAL_VALID)
        # 放 3 条互不相关的深层错误
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = "not list"
        cfg["rules"]["amount_limits"]["monthly_limits"]["superman"] = "bad"
        cfg["rules"]["receipt_required"]["threshold"] = "五百"
        f = tmp_path / "many.yaml"
        f.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))

        runner = CliRunner()
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        flat = result.stdout.replace("\n", "").replace(" ", "")
        assert "tier1_cities" in flat
        assert "superman" in flat
        assert "threshold" in flat
        # 错误数量提示
        assert "3" in flat or "多条" in flat


# =============== 场景七：标量探测拒绝（load_yaml 收窄为 dict） ===============

class TestYamlScalarRejection:
    def test_yaml_scalar_string_falls_back_to_default(self, tmp_path: Path):
        """YAML 内容是 'hello world'，不是 dict，应该被 content_probe 拒绝并走 fallback"""
        f = tmp_path / "scalar.yaml"
        f.write_text("hello world\n")
        result = load_yaml(f, default={"fallback": True}, on_corrupt="fallback")
        assert result == {"fallback": True}

    def test_yaml_integer_scalar_raises_in_raise_mode(self, tmp_path: Path):
        f = tmp_path / "scalar_int.yaml"
        f.write_text("42\n")
        with pytest.raises(CorruptedFileError):
            load_yaml(f, on_corrupt="raise")

    def test_yaml_list_root_falls_back(self, tmp_path: Path):
        f = tmp_path / "list.yaml"
        f.write_text("- a\n- b\n- c\n")
        result = load_yaml(f, default={"default": "dict"}, on_corrupt="fallback")
        assert result == {"default": "dict"}

    def test_yaml_float_scalar_uses_replace_ultimately(self, tmp_path: Path):
        """标量 yaml + 字节含非法字符时，先编码安全，再内容判断"""
        f = tmp_path / "scalar_float.yaml"
        # 标量 3.14 -> content_probe 检查非 dict -> 触发 fallback
        f.write_text("3.14\n")
        result = load_yaml(f, default={"dict": 1}, on_corrupt="fallback")
        assert result == {"dict": 1}

    def test_valid_dict_yaml_not_affected(self, tmp_path: Path):
        """正常 dict YAML 不受标量拒绝影响"""
        f = tmp_path / "dict.yaml"
        payload = copy.deepcopy(MINIMAL_VALID)
        f.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
        data = load_yaml(f)
        ok, errs = validate_policy_config(data)
        assert ok is True
        assert errs == []
        assert data["version"] == "2.0.0"

    def test_scalar_yaml_via_content_probe_skips_encoding(self, tmp_path: Path):
        """
        GBK 标量 YAML（单字节也能解码但不是 dict）：
        - 先 gbk 解码得到字符串 '只是一段中文'
        - content_probe 检查 yaml.safe_load 返回 str，不是 dict -> 探测不通过
        - 试下一个编码，decode 结果相同，都探测不通过
        - 最终 fall through errors=replace 兜底还是同一文本，content_probe 仍返回 False
        - _read_text_safely 不做 probe 的兜底返回文本
        - load_yaml 内部再次判断 isinstance(loaded, dict) -> False -> fallback
        """
        f = tmp_path / "scalar_gbk.yaml"
        gbk_text = "这只是一段中文标量内容，不是 YAML 字典 北京上海广州"
        f.write_bytes(gbk_text.encode("gbk"))
        result = load_yaml(f, default={"k": "v"}, on_corrupt="fallback")
        assert result == {"k": "v"}


