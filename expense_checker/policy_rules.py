from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config_schema import ConfigValidationError, validate_policy_config
from .models import EmployeeLevel, ExpenseType

logger = logging.getLogger(__name__)

YAML_CONFIG_ENV = "EXPENSE_POLICY_CONFIG"
BUILTIN_CONFIG_PATH = Path(__file__).parent / "config" / "policy_rules.yaml"

DEFAULT_POLICY_RULES: Dict[str, Any] = {
    "version": "1.0.0",
    "name": "公司财务报销政策",
    "last_updated": "2025-01-01",
    "rules": {
        "amount_limits": {
            "rule_id": "R001",
            "rule_name": "单笔/单类金额上限",
            "description": "根据职级设定不同费用类型的单笔/月度报销上限",
            "per_transaction_limits": {
                "intern": {"meal": 80.0, "transportation": 200.0, "accommodation": 400.0, "entertainment": 300.0},
                "junior": {"meal": 120.0, "transportation": 500.0, "accommodation": 600.0, "entertainment": 800.0},
                "middle": {"meal": 200.0, "transportation": 1000.0, "accommodation": 1000.0, "entertainment": 1500.0},
                "senior": {"meal": 300.0, "transportation": 2000.0, "accommodation": 1500.0, "entertainment": 3000.0},
                "manager": {"meal": 400.0, "transportation": 3000.0, "accommodation": 2500.0, "entertainment": 5000.0},
                "director": {"meal": 600.0, "transportation": 5000.0, "accommodation": 4000.0, "entertainment": 10000.0},
                "vp": {"meal": 1000.0, "transportation": 10000.0, "accommodation": 8000.0, "entertainment": 20000.0},
            },
            "monthly_limits": {
                "intern": 2000.0,
                "junior": 5000.0,
                "middle": 10000.0,
                "senior": 20000.0,
                "manager": 50000.0,
                "director": 100000.0,
                "vp": 500000.0,
            },
        },
        "receipt_required": {"rule_id": "R002", "rule_name": "发票要求", "description": "超过一定金额必须提供发票", "threshold": 200.0},
        "meal_per_day_limit": {
            "rule_id": "R003",
            "rule_name": "每日餐费上限",
            "description": "单日餐费报销总额不得超过上限",
            "limits": {
                "intern": 150.0,
                "junior": 250.0,
                "middle": 400.0,
                "senior": 600.0,
                "manager": 800.0,
                "director": 1200.0,
                "vp": 2000.0,
            },
        },
        "travel_accommodation_city_tier": {
            "rule_id": "R004",
            "rule_name": "出差住宿城市分级标准",
            "description": "根据出差城市级别设定住宿标准",
            "tier1_cities": ["北京", "上海", "广州", "深圳", "杭州"],
            "tier2_cities": ["成都", "重庆", "武汉", "南京", "西安", "苏州", "天津", "厦门"],
            "multipliers": {"tier1": 1.5, "tier2": 1.2, "tier3": 1.0},
        },
        "entertainment_requirements": {
            "rule_id": "R005",
            "rule_name": "招待费特殊要求",
            "description": "招待费必须注明参与人员和事由",
            "min_participants": 2,
            "description_min_length": 5,
        },
        "expense_date_validity": {
            "rule_id": "R006",
            "rule_name": "费用时效性",
            "description": "费用发生日期必须在报销提交日前90天内",
            "max_days_before_submit": 90,
            "future_dates_allowed": False,
        },
        "department_quotas": {
            "rule_id": "R007",
            "rule_name": "部门预算配额",
            "description": "各部门月度培训和招待费限额",
            "training_monthly": {
                "engineering": 50000.0, "sales": 30000.0, "marketing": 40000.0, "hr": 20000.0,
                "finance": 10000.0, "operations": 25000.0, "admin": 15000.0,
            },
            "entertainment_monthly": {
                "engineering": 20000.0, "sales": 80000.0, "marketing": 50000.0, "hr": 10000.0,
                "finance": 5000.0, "operations": 15000.0, "admin": 10000.0,
            },
        },
    },
}


def load_rules_from_yaml(yaml_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    从 YAML 文件加载规则。优先级：
    1. 传入的 yaml_path 参数
    2. 环境变量 EXPENSE_POLICY_CONFIG 指定的路径
    3. 包内内置 config/policy_rules.yaml
    失败（文件不存在/解析失败/结构校验失败）时返回 None 让调用方回退到默认配置。
    结构校验失败会通过 logging.warning 输出具体错误，便于用户排查。
    """
    candidate = None
    if yaml_path:
        candidate = Path(yaml_path)
    else:
        env_val = os.environ.get(YAML_CONFIG_ENV)
        if env_val:
            candidate = Path(env_val)
        elif BUILTIN_CONFIG_PATH.exists():
            candidate = BUILTIN_CONFIG_PATH

    if candidate is None or not candidate.exists():
        return None

    try:
        import yaml
    except ImportError:
        return None

    try:
        with open(candidate, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return None
        loaded = yaml.safe_load(content)
        if not isinstance(loaded, dict) or "rules" not in loaded:
            logger.warning(
                "配置文件 %s 结构不合法（根节点非 dict 或缺少 rules 键），已忽略并回退到内置默认规则",
                candidate,
            )
            return None
        ok, errs = validate_policy_config(loaded)
        if ok:
            return loaded
        # 多条错误，日志摘要前 3 条
        if len(errs) == 1:
            first_path, first_msg = errs[0]
            logger.warning(
                "配置文件 %s 校验失败（[%s] %s），共 1 条错误，已忽略并回退到内置默认规则。"
                " 运行 `expense-checker validate-config %s` 查看详细错误。",
                candidate, first_path, first_msg, candidate,
            )
        else:
            first_path, first_msg = errs[0]
            logger.warning(
                "配置文件 %s 校验失败，共 %d 条错误（首条: [%s] %s），已忽略并回退到内置默认规则。"
                " 运行 `expense-checker validate-config %s` 查看全部错误。",
                candidate, len(errs), first_path, first_msg, candidate,
            )
        return None
    except Exception as e:
        logger.warning(
            "读取配置文件 %s 失败（%s），已忽略并回退到内置默认规则",
            candidate, type(e).__name__,
        )
        return None


def validate_policy_file(yaml_path: Optional[Path] = None) -> Tuple[bool, List[Tuple[str, str]]]:
    """
    显式校验一个政策配置文件（供 CLI validate-config 子命令使用）。

    返回:
        (是否合法, 错误列表 [(path, message), ...])
    """
    candidate = None
    if yaml_path:
        candidate = Path(yaml_path)
    else:
        env_val = os.environ.get(YAML_CONFIG_ENV)
        if env_val:
            candidate = Path(env_val)
        elif BUILTIN_CONFIG_PATH.exists():
            candidate = BUILTIN_CONFIG_PATH

    errors: List[Tuple[str, str]] = []
    if candidate is None:
        errors.append(("", "未指定配置文件路径，且默认配置不存在"))
        return False, errors

    if not candidate.exists():
        errors.append(("", f"文件不存在: {candidate}"))
        return False, errors

    try:
        import yaml
    except ImportError as e:
        errors.append(("", f"缺少 PyYAML 依赖: {e}"))
        return False, errors

    try:
        with open(candidate, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            errors.append(("", "文件为空"))
            return False, errors
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as e:
        errors.append(("", f"YAML 解析错误: {e}"))
        return False, errors
    except UnicodeDecodeError as e:
        errors.append(("", f"文件编码错误（非 UTF-8）: {e}"))
        return False, errors
    except OSError as e:
        errors.append(("", f"读取文件失败: {e}"))
        return False, errors

    # 结构校验：validate_policy_config 已完整收集多条错误
    ok, deep_errors = validate_policy_config(loaded)
    if deep_errors:
        errors.extend(deep_errors)
    return ok, errors


def _normalize_rules(rules: Dict[str, Any]) -> Dict[str, Any]:
    """兼容 Enum key 和 string key，统一内部使用 string key"""
    if not isinstance(rules, dict):
        return rules
    normalized: Dict[str, Any] = {}
    for k, v in rules.items():
        if isinstance(k, (EmployeeLevel, ExpenseType)):
            nk = k.value
        else:
            nk = str(k)
        if isinstance(v, dict):
            normalized[nk] = _normalize_rules(v)
        elif isinstance(v, list):
            normalized[nk] = [
                _normalize_rules(x) if isinstance(x, dict) else x for x in v
            ]
        else:
            normalized[nk] = v
    return normalized


def load_default_rules(yaml_path: Optional[Path] = None) -> Dict[str, Any]:
    """加载规则：优先 YAML 配置文件，失败则回退到内置 DEFAULT_POLICY_RULES"""
    yaml_rules = load_rules_from_yaml(yaml_path)
    base = yaml_rules if yaml_rules else DEFAULT_POLICY_RULES
    return _normalize_rules(base)


def _key(obj, k):
    if isinstance(k, (EmployeeLevel, ExpenseType)):
        return k.value
    return k


def get_amount_limit(rules: Dict[str, Any], level: EmployeeLevel, expense_type: ExpenseType) -> Optional[float]:
    limits = (
        rules.get("rules", {})
        .get("amount_limits", {})
        .get("per_transaction_limits", {})
        .get(_key(rules, level), {})
    )
    return limits.get(_key(rules, expense_type))


def get_monthly_limit(rules: Dict[str, Any], level: EmployeeLevel) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("amount_limits", {})
        .get("monthly_limits", {})
        .get(_key(rules, level))
    )


def get_meal_daily_limit(rules: Dict[str, Any], level: EmployeeLevel) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("meal_per_day_limit", {})
        .get("limits", {})
        .get(_key(rules, level))
    )


def get_city_tier_multiplier(rules: Dict[str, Any], city: Optional[str]) -> float:
    if not city:
        return 1.0
    city_rules = rules.get("rules", {}).get("travel_accommodation_city_tier", {})
    multipliers = city_rules.get("multipliers", {"tier1": 1.5, "tier2": 1.2, "tier3": 1.0})
    if city in city_rules.get("tier1_cities", []):
        return multipliers["tier1"]
    elif city in city_rules.get("tier2_cities", []):
        return multipliers["tier2"]
    return multipliers["tier3"]


def get_tier1_cities(rules: Dict[str, Any]) -> List[str]:
    return list(
        rules.get("rules", {})
        .get("travel_accommodation_city_tier", {})
        .get("tier1_cities", [])
    )


def get_tier2_cities(rules: Dict[str, Any]) -> List[str]:
    return list(
        rules.get("rules", {})
        .get("travel_accommodation_city_tier", {})
        .get("tier2_cities", [])
    )


def get_all_levels(rules: Dict[str, Any]) -> List[str]:
    """从配置返回所有职级"""
    limits = (
        rules.get("rules", {})
        .get("amount_limits", {})
        .get("monthly_limits", {})
    )
    return list(limits.keys())


def get_department_training_quota(rules: Dict[str, Any], department: str) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("department_quotas", {})
        .get("training_monthly", {})
        .get(department.lower())
    )


def get_department_entertainment_quota(rules: Dict[str, Any], department: str) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("department_quotas", {})
        .get("entertainment_monthly", {})
        .get(department.lower())
    )
