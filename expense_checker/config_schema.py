from __future__ import annotations

from typing import Any, Dict, List


class ConfigValidationError(Exception):
    """
    配置结构校验异常。

    message 中应包含校验失败的键路径（使用点表示法）以及具体原因，
    例如："rules.travel_accommodation_city_tier.tier1_cities 期望为 list，实际为 str"
    """

    def __init__(self, message: str, path: str = ""):
        self.path = path
        super().__init__(message)


_VALID_LEVELS = {"intern", "junior", "middle", "senior", "manager", "director", "vp"}
_VALID_EXPENSE_TYPES = {"meal", "transportation", "accommodation", "entertainment", "training", "other"}


def _join_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def _require_key(obj: Dict[str, Any], key: str, path: str) -> Any:
    if key not in obj:
        raise ConfigValidationError(
            f"配置缺少必需键: '{_join_path(path, key)}'",
            path=_join_path(path, key),
        )
    return obj[key]


def _check_type(value: Any, expected_type: type, path: str) -> None:
    if not isinstance(value, expected_type):
        name = expected_type.__name__
        actual = type(value).__name__
        raise ConfigValidationError(
            f"键 '{path}' 类型错误: 期望 {name}，实际为 {actual}",
            path=path,
        )


def _check_dict_items_type(d: Dict[str, Any], value_type, path: str) -> None:
    """字典中每个 key 对应的值都必须是 value_type（支持单个 type 或 tuple）"""
    if isinstance(value_type, tuple):
        type_names = " or ".join(t.__name__ for t in value_type)
    else:
        type_names = value_type.__name__
    for k, v in d.items():
        k_path = _join_path(path, str(k))
        if not isinstance(v, value_type):
            actual = type(v).__name__
            raise ConfigValidationError(
                f"键 '{k_path}' 类型错误: 期望 {type_names}，实际为 {actual}",
                path=k_path,
            )


def _validate_amount_limits(amount: Dict[str, Any], path: str) -> None:
    per = _require_key(amount, "per_transaction_limits", path)
    _check_type(per, dict, _join_path(path, "per_transaction_limits"))
    if not per:
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'per_transaction_limits')}' 不能为空字典",
            path=_join_path(path, "per_transaction_limits"),
        )
    for level_name, level_map in per.items():
        level_path = _join_path(_join_path(path, "per_transaction_limits"), level_name)
        if level_name not in _VALID_LEVELS:
            raise ConfigValidationError(
                f"键 '{level_path}' 使用了未知职级: '{level_name}'，合法值: {sorted(_VALID_LEVELS)}",
                path=level_path,
            )
        _check_type(level_map, dict, level_path)
        _check_dict_items_type(level_map, (int, float), level_path)

    monthly = _require_key(amount, "monthly_limits", path)
    _check_type(monthly, dict, _join_path(path, "monthly_limits"))
    if not monthly:
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'monthly_limits')}' 不能为空字典",
            path=_join_path(path, "monthly_limits"),
        )
    for level_name, limit in monthly.items():
        level_path = _join_path(_join_path(path, "monthly_limits"), level_name)
        if level_name not in _VALID_LEVELS:
            raise ConfigValidationError(
                f"键 '{level_path}' 使用了未知职级: '{level_name}'，合法值: {sorted(_VALID_LEVELS)}",
                path=level_path,
            )
        if not isinstance(limit, (int, float)):
            raise ConfigValidationError(
                f"键 '{level_path}' 类型错误: 期望数字，实际为 {type(limit).__name__}",
                path=level_path,
            )


def _validate_meal_limits(meal: Dict[str, Any], path: str) -> None:
    limits = _require_key(meal, "limits", path)
    _check_type(limits, dict, _join_path(path, "limits"))
    if not limits:
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'limits')}' 不能为空字典",
            path=_join_path(path, "limits"),
        )
    for level_name, limit in limits.items():
        level_path = _join_path(_join_path(path, "limits"), level_name)
        if level_name not in _VALID_LEVELS:
            raise ConfigValidationError(
                f"键 '{level_path}' 使用了未知职级: '{level_name}'，合法值: {sorted(_VALID_LEVELS)}",
                path=level_path,
            )
        if not isinstance(limit, (int, float)):
            raise ConfigValidationError(
                f"键 '{level_path}' 类型错误: 期望数字，实际为 {type(limit).__name__}",
                path=level_path,
            )


def _validate_city_tier(city_tier: Dict[str, Any], path: str) -> None:
    t1 = _require_key(city_tier, "tier1_cities", path)
    _check_type(t1, list, _join_path(path, "tier1_cities"))
    for i, item in enumerate(t1):
        if not isinstance(item, str):
            raise ConfigValidationError(
                f"键 '{_join_path(path, 'tier1_cities')}[{i}]' 类型错误: 期望 str，实际为 {type(item).__name__}",
                path=_join_path(path, "tier1_cities"),
            )

    t2 = _require_key(city_tier, "tier2_cities", path)
    _check_type(t2, list, _join_path(path, "tier2_cities"))
    for i, item in enumerate(t2):
        if not isinstance(item, str):
            raise ConfigValidationError(
                f"键 '{_join_path(path, 'tier2_cities')}[{i}]' 类型错误: 期望 str，实际为 {type(item).__name__}",
                path=_join_path(path, "tier2_cities"),
            )

    mult = _require_key(city_tier, "multipliers", path)
    _check_type(mult, dict, _join_path(path, "multipliers"))
    for tier in ("tier1", "tier2", "tier3"):
        tier_path = _join_path(_join_path(path, "multipliers"), tier)
        if tier not in mult:
            raise ConfigValidationError(
                f"配置缺少必需键: '{tier_path}'",
                path=tier_path,
            )
        if not isinstance(mult[tier], (int, float)):
            raise ConfigValidationError(
                f"键 '{tier_path}' 类型错误: 期望数字，实际为 {type(mult[tier]).__name__}",
                path=tier_path,
            )


def _validate_receipt_required(rr: Dict[str, Any], path: str) -> None:
    t = _require_key(rr, "threshold", path)
    if not isinstance(t, (int, float)):
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'threshold')}' 类型错误: 期望数字，实际为 {type(t).__name__}",
            path=_join_path(path, "threshold"),
        )


def _validate_entertainment(ent: Dict[str, Any], path: str) -> None:
    mp = _require_key(ent, "min_participants", path)
    if not isinstance(mp, int) or isinstance(mp, bool):
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'min_participants')}' 类型错误: 期望 int，实际为 {type(mp).__name__}",
            path=_join_path(path, "min_participants"),
        )
    dl = _require_key(ent, "description_min_length", path)
    if not isinstance(dl, int) or isinstance(dl, bool):
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'description_min_length')}' 类型错误: 期望 int，实际为 {type(dl).__name__}",
            path=_join_path(path, "description_min_length"),
        )


def _validate_expense_date(ed: Dict[str, Any], path: str) -> None:
    md = _require_key(ed, "max_days_before_submit", path)
    if not isinstance(md, int) or isinstance(md, bool):
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'max_days_before_submit')}' 类型错误: 期望 int，实际为 {type(md).__name__}",
            path=_join_path(path, "max_days_before_submit"),
        )
    fda = _require_key(ed, "future_dates_allowed", path)
    if not isinstance(fda, bool):
        raise ConfigValidationError(
            f"键 '{_join_path(path, 'future_dates_allowed')}' 类型错误: 期望 bool，实际为 {type(fda).__name__}",
            path=_join_path(path, "future_dates_allowed"),
        )


def _validate_department_quotas(dq: Dict[str, Any], path: str) -> None:
    for sub in ("training_monthly", "entertainment_monthly"):
        sub_path = _join_path(path, sub)
        sub_val = _require_key(dq, sub, path)
        _check_type(sub_val, dict, sub_path)
        _check_dict_items_type(sub_val, (int, float), sub_path)


def validate_policy_config(config: Any) -> Dict[str, Any]:
    """
    校验报销政策配置结构。

    校验项（均递归检查类型）：
    - 根节点必须为 dict
    - 顶层必须有 version(str)、name(str)、rules(dict) 键
    - rules 下 7 条规则子键必须存在并符合各自结构约束：
      * amount_limits         → per_transaction_limits(levels→types→number) + monthly_limits(levels→number)
      * receipt_required      → threshold(number)
      * meal_per_day_limit    → limits(levels→number)
      * travel_accommodation_city_tier → tier1_cities(list[str]) + tier2_cities(list[str]) + multipliers(dict)
      * entertainment_requirements     → min_participants(int) + description_min_length(int)
      * expense_date_validity          → max_days_before_submit(int) + future_dates_allowed(bool)
      * department_quotas              → training_monthly + entertainment_monthly(dict)

    参数:
        config: 解析后的配置对象（一般是 yaml.safe_load 或 json.loads 返回值）

    返回:
        规范化后的配置 dict（若内部有 Enum key 需调用方另行 normalize）

    抛出:
        ConfigValidationError: 键缺失或类型不匹配，message 中带具体路径
    """
    if not isinstance(config, dict):
        raise ConfigValidationError(
            f"配置根节点类型错误: 期望 dict，实际为 {type(config).__name__}",
            path="",
        )

    version = _require_key(config, "version", "")
    if not isinstance(version, str):
        raise ConfigValidationError(
            f"键 'version' 类型错误: 期望 str，实际为 {type(version).__name__}",
            path="version",
        )

    name = _require_key(config, "name", "")
    if not isinstance(name, str):
        raise ConfigValidationError(
            f"键 'name' 类型错误: 期望 str，实际为 {type(name).__name__}",
            path="name",
        )

    rules = _require_key(config, "rules", "")
    _check_type(rules, dict, "rules")

    # 逐条校验 7 类规则子结构
    required_rules = {
        "amount_limits": _validate_amount_limits,
        "receipt_required": _validate_receipt_required,
        "meal_per_day_limit": _validate_meal_limits,
        "travel_accommodation_city_tier": _validate_city_tier,
        "entertainment_requirements": _validate_entertainment,
        "expense_date_validity": _validate_expense_date,
        "department_quotas": _validate_department_quotas,
    }
    for key, validator in required_rules.items():
        val = _require_key(rules, key, "rules")
        _check_type(val, dict, f"rules.{key}")
        validator(val, f"rules.{key}")

    return config
