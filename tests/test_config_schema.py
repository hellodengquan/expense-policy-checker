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
        result = validate_policy_config(copy.deepcopy(MINIMAL_VALID))
        assert result["version"] == "2.0.0"
        assert "火星市" in result["rules"]["travel_accommodation_city_tier"]["tier1_cities"]

    def test_builtin_yaml_matches_schema(self):
        # 验证出厂 policy_rules.yaml 通过校验
        with open(BUILTIN_CONFIG_PATH, "r", encoding="utf-8") as f:
            builtin = yaml.safe_load(f)
        validate_policy_config(builtin)

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
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "version" in exc.value.path
        assert "缺少必需键" in str(exc.value)

    def test_root_missing_rules(self):
        cfg = {"version": "1.0.0", "name": "x"}
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert exc.value.path == "rules"

    def test_city_tier_missing_tier1_cities(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "tier1_cities" in exc.value.path

    def test_city_tier_missing_tier2_cities(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["travel_accommodation_city_tier"]["tier2_cities"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "tier2_cities" in exc.value.path

    def test_city_tier_missing_tier1_multiplier(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["travel_accommodation_city_tier"]["multipliers"]["tier1"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "multipliers.tier1" in exc.value.path

    def test_amount_limits_missing_per_transaction(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["amount_limits"]["per_transaction_limits"]
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "per_transaction_limits" in exc.value.path

    def test_meal_missing_limits(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["meal_per_day_limit"]["limits"]
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

    def test_entertainment_missing_min_participants(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["entertainment_requirements"]["min_participants"]
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

    def test_expense_date_missing_future_flag(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        del cfg["rules"]["expense_date_validity"]["future_dates_allowed"]
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

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
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config([1, 2, 3])
        assert "根节点" in str(exc.value)

    def test_version_not_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["version"] = 123
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert exc.value.path == "version"
        assert "期望 str" in str(exc.value)

    def test_rules_not_dict(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"] = "a string"
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert exc.value.path == "rules"

    def test_tier1_cities_is_str_instead_of_list(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = "北京,上海"
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "tier1_cities" in exc.value.path
        assert "期望 list" in str(exc.value)

    def test_tier2_cities_item_is_int(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["tier2_cities"] = ["成都", 123]
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "tier2_cities" in exc.value.path

    def test_multipliers_tier1_not_numeric(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["multipliers"]["tier1"] = "很贵"
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "tier1" in exc.value.path

    def test_monthly_limits_unknown_level(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["amount_limits"]["monthly_limits"]["superman"] = 99999
        with pytest.raises(ConfigValidationError) as exc:
            validate_policy_config(cfg)
        assert "superman" in exc.value.path
        assert "未知职级" in str(exc.value)

    def test_per_transaction_amount_not_numeric(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["amount_limits"]["per_transaction_limits"]["middle"]["meal"] = "两百块"
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

    def test_receipt_threshold_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["receipt_required"]["threshold"] = "五百"
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

    def test_min_participants_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["entertainment_requirements"]["min_participants"] = "两个人"
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

    def test_future_dates_allowed_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["expense_date_validity"]["future_dates_allowed"] = "是的"
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)

    def test_department_quota_value_is_str(self):
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["department_quotas"]["training_monthly"]["engineering"] = "很多"
        with pytest.raises(ConfigValidationError):
            validate_policy_config(cfg)


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
