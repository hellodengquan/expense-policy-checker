from __future__ import annotations

from typing import Any, Dict, List, Tuple


class ConfigValidationError(Exception):
    """
    配置结构校验异常（兼容保留）。

    新版本 `validate_policy_config` 不主动抛出此异常，而是返回错误列表；
    但保留此类，供：
    - 旧代码（外部可能仍在 try/except 捕获）兼容
    - validate_policy_file 等场景构造结构化错误时使用
    """

    def __init__(self, message: str, path: str = ""):
        self.path = path
        super().__init__(message)


ConfigError = Tuple[str, str]  # (path, message)


_VALID_LEVELS = {"intern", "junior", "middle", "senior", "manager", "director", "vp"}


def _join_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def _type_names(value_type) -> str:
    if isinstance(value_type, tuple):
        return " or ".join(t.__name__ for t in value_type)
    return value_type.__name__


def _must_be_dict(obj: Any, path: str, errors: List[ConfigError]) -> bool:
    if not isinstance(obj, dict):
        errors.append((path, f"期望 dict，实际为 {type(obj).__name__}"))
        return False
    return True


def _require_key(
    obj: Dict[str, Any], key: str, path: str, errors: List[ConfigError]
) -> bool:
    """检查 key 是否存在。True=键存在"""
    if key not in obj:
        errors.append(
            (_join_path(path, key), f"缺少必需键 '{_join_path(path, key)}'")
        )
        return False
    return True


def _check_type(
    value: Any, expected_type, path: str, errors: List[ConfigError]
) -> bool:
    if not isinstance(value, expected_type):
        errors.append(
            (path, f"类型错误: 期望 {_type_names(expected_type)}，实际为 {type(value).__name__}")
        )
        return False
    return True


def _check_dict_items_type(
    d: Dict[str, Any], value_type, path: str, errors: List[ConfigError]
) -> None:
    """字典中每个 value 的类型检查"""
    for k, v in d.items():
        k_path = _join_path(path, str(k))
        if not isinstance(v, value_type):
            errors.append(
                (k_path, f"类型错误: 期望 {_type_names(value_type)}，实际为 {type(v).__name__}")
            )


def _validate_amount_limits(amount: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(amount, path, errors):
        return
    if _require_key(amount, "per_transaction_limits", path, errors):
        per = amount["per_transaction_limits"]
        per_path = _join_path(path, "per_transaction_limits")
        if _must_be_dict(per, per_path, errors):
            if not per:
                errors.append((per_path, "不能为空字典"))
            else:
                for level_name, level_map in per.items():
                    level_path = _join_path(per_path, level_name)
                    if level_name not in _VALID_LEVELS:
                        errors.append(
                            (level_path, f"使用了未知职级: '{level_name}'，合法值: {sorted(_VALID_LEVELS)}")
                        )
                    if _must_be_dict(level_map, level_path, errors):
                        _check_dict_items_type(level_map, (int, float), level_path, errors)

    if _require_key(amount, "monthly_limits", path, errors):
        monthly = amount["monthly_limits"]
        monthly_path = _join_path(path, "monthly_limits")
        if _must_be_dict(monthly, monthly_path, errors):
            if not monthly:
                errors.append((monthly_path, "不能为空字典"))
            else:
                for level_name, limit in monthly.items():
                    level_path = _join_path(monthly_path, level_name)
                    if level_name not in _VALID_LEVELS:
                        errors.append(
                            (level_path, f"使用了未知职级: '{level_name}'，合法值: {sorted(_VALID_LEVELS)}")
                        )
                    if not isinstance(limit, (int, float)):
                        errors.append(
                            (level_path, f"类型错误: 期望数字，实际为 {type(limit).__name__}")
                        )


def _validate_meal_limits(meal: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(meal, path, errors):
        return
    if _require_key(meal, "limits", path, errors):
        limits = meal["limits"]
        limits_path = _join_path(path, "limits")
        if _must_be_dict(limits, limits_path, errors):
            if not limits:
                errors.append((limits_path, "不能为空字典"))
            else:
                for level_name, limit in limits.items():
                    level_path = _join_path(limits_path, level_name)
                    if level_name not in _VALID_LEVELS:
                        errors.append(
                            (level_path, f"使用了未知职级: '{level_name}'，合法值: {sorted(_VALID_LEVELS)}")
                        )
                    if not isinstance(limit, (int, float)):
                        errors.append(
                            (level_path, f"类型错误: 期望数字，实际为 {type(limit).__name__}")
                        )


def _validate_city_tier(city_tier: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(city_tier, path, errors):
        return
    # tier1
    if _require_key(city_tier, "tier1_cities", path, errors):
        t1 = city_tier["tier1_cities"]
        t1_path = _join_path(path, "tier1_cities")
        if _check_type(t1, list, t1_path, errors):
            for i, item in enumerate(t1):
                if not isinstance(item, str):
                    errors.append(
                        (f"{t1_path}[{i}]", f"列表元素类型错误: 期望 str，实际为 {type(item).__name__}")
                    )
    # tier2
    if _require_key(city_tier, "tier2_cities", path, errors):
        t2 = city_tier["tier2_cities"]
        t2_path = _join_path(path, "tier2_cities")
        if _check_type(t2, list, t2_path, errors):
            for i, item in enumerate(t2):
                if not isinstance(item, str):
                    errors.append(
                        (f"{t2_path}[{i}]", f"列表元素类型错误: 期望 str，实际为 {type(item).__name__}")
                    )
    # multipliers
    if _require_key(city_tier, "multipliers", path, errors):
        mult = city_tier["multipliers"]
        mult_path = _join_path(path, "multipliers")
        if _must_be_dict(mult, mult_path, errors):
            for tier in ("tier1", "tier2", "tier3"):
                tier_path = _join_path(mult_path, tier)
                if tier not in mult:
                    errors.append((tier_path, f"缺少必需键 '{tier_path}'"))
                elif not isinstance(mult[tier], (int, float)):
                    errors.append(
                        (tier_path, f"类型错误: 期望数字，实际为 {type(mult[tier]).__name__}")
                    )


def _validate_receipt_required(rr: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(rr, path, errors):
        return
    if _require_key(rr, "threshold", path, errors):
        t = rr["threshold"]
        if not isinstance(t, (int, float)):
            errors.append(
                (_join_path(path, "threshold"), f"类型错误: 期望数字，实际为 {type(t).__name__}")
            )


def _validate_entertainment(ent: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(ent, path, errors):
        return
    if _require_key(ent, "min_participants", path, errors):
        mp = ent["min_participants"]
        if (not isinstance(mp, int)) or isinstance(mp, bool):
            errors.append(
                (_join_path(path, "min_participants"),
                 f"类型错误: 期望 int，实际为 {type(mp).__name__}")
            )
    if _require_key(ent, "description_min_length", path, errors):
        dl = ent["description_min_length"]
        if (not isinstance(dl, int)) or isinstance(dl, bool):
            errors.append(
                (_join_path(path, "description_min_length"),
                 f"类型错误: 期望 int，实际为 {type(dl).__name__}")
            )


def _validate_expense_date(ed: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(ed, path, errors):
        return
    if _require_key(ed, "max_days_before_submit", path, errors):
        md = ed["max_days_before_submit"]
        if (not isinstance(md, int)) or isinstance(md, bool):
            errors.append(
                (_join_path(path, "max_days_before_submit"),
                 f"类型错误: 期望 int，实际为 {type(md).__name__}")
            )
    if _require_key(ed, "future_dates_allowed", path, errors):
        fda = ed["future_dates_allowed"]
        if not isinstance(fda, bool):
            errors.append(
                (_join_path(path, "future_dates_allowed"),
                 f"类型错误: 期望 bool，实际为 {type(fda).__name__}")
            )


def _validate_department_quotas(dq: Dict[str, Any], path: str, errors: List[ConfigError]) -> None:
    if not _must_be_dict(dq, path, errors):
        return
    for sub in ("training_monthly", "entertainment_monthly"):
        sub_path = _join_path(path, sub)
        if _require_key(dq, sub, path, errors):
            sub_val = dq[sub]
            if _must_be_dict(sub_val, sub_path, errors):
                _check_dict_items_type(sub_val, (int, float), sub_path, errors)


_REQUIRED_RULES: Dict[str, Any] = {
    "amount_limits": _validate_amount_limits,
    "receipt_required": _validate_receipt_required,
    "meal_per_day_limit": _validate_meal_limits,
    "travel_accommodation_city_tier": _validate_city_tier,
    "entertainment_requirements": _validate_entertainment,
    "expense_date_validity": _validate_expense_date,
    "department_quotas": _validate_department_quotas,
}


def validate_policy_config(
    config: Any,
    *,
    raise_on_error: bool = False,
) -> Tuple[bool, List[ConfigError]]:
    """
    校验报销政策配置结构（纯函数形式，收集完整错误列表）。

    校验项（完整遍历，遇到错误不中断，而是记录后继续）：
    - 根节点必须为 dict
    - 顶层必须有 version(str)、name(str)、rules(dict) 键
    - rules 下 7 条规则子键必须存在并符合各自结构约束

    参数:
        config: 解析后的配置对象
        raise_on_error: 若为 True，当存在至少一条错误时，以首条错误抛 ConfigValidationError
                       （用于兼容老代码依赖抛异常的行为）

    返回:
        (是否合法, 错误列表 [(path, message), ...])
        - 合法时：错误列表为空
        - 不合法时：错误列表按遍历顺序排列，可能含多条
    """
    errors: List[ConfigError] = []

    if not isinstance(config, dict):
        errors.append(("", f"配置根节点类型错误: 期望 dict，实际为 {type(config).__name__}"))
        if raise_on_error and errors:
            path, msg = errors[0]
            raise ConfigValidationError(msg, path=path)
        return False, errors

    # version
    if "version" not in config:
        errors.append(("version", "缺少必需键 'version'"))
    elif not isinstance(config["version"], str):
        errors.append(("version", f"类型错误: 期望 str，实际为 {type(config['version']).__name__}"))

    # name
    if "name" not in config:
        errors.append(("name", "缺少必需键 'name'"))
    elif not isinstance(config["name"], str):
        errors.append(("name", f"类型错误: 期望 str，实际为 {type(config['name']).__name__}"))

    # rules 存在性 + 类型
    if "rules" not in config:
        errors.append(("rules", "缺少必需键 'rules'"))
    elif not isinstance(config["rules"], dict):
        errors.append(("rules", f"类型错误: 期望 dict，实际为 {type(config['rules']).__name__}"))
    else:
        rules = config["rules"]
        # 检查 7 条子规则存在性 + 类型 + 深入校验
        for key, validator in _REQUIRED_RULES.items():
            key_path = f"rules.{key}"
            if key not in rules:
                errors.append((key_path, f"缺少必需键 '{key_path}'"))
                continue
            if not isinstance(rules[key], dict):
                errors.append((key_path, f"类型错误: 期望 dict，实际为 {type(rules[key]).__name__}"))
                continue
            validator(rules[key], key_path, errors)

    ok = len(errors) == 0

    if raise_on_error and not ok:
        path, msg = errors[0]
        raise ConfigValidationError(msg, path=path)

    return ok, errors
