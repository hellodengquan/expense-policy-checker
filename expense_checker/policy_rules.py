from __future__ import annotations

from typing import Dict, List, Optional

from .models import EmployeeLevel, ExpenseType


DEFAULT_POLICY_RULES: Dict = {
    "version": "1.0.0",
    "name": "公司财务报销政策",
    "last_updated": "2025-01-01",
    "rules": {
        "amount_limits": {
            "rule_id": "R001",
            "rule_name": "单笔/单类金额上限",
            "description": "根据职级设定不同费用类型的单笔/月度报销上限",
            "per_transaction_limits": {
                EmployeeLevel.INTERN: {
                    ExpenseType.MEAL: 80.0,
                    ExpenseType.TRANSPORTATION: 200.0,
                    ExpenseType.ACCOMMODATION: 400.0,
                    ExpenseType.ENTERTAINMENT: 300.0,
                },
                EmployeeLevel.JUNIOR: {
                    ExpenseType.MEAL: 120.0,
                    ExpenseType.TRANSPORTATION: 500.0,
                    ExpenseType.ACCOMMODATION: 600.0,
                    ExpenseType.ENTERTAINMENT: 800.0,
                },
                EmployeeLevel.MIDDLE: {
                    ExpenseType.MEAL: 200.0,
                    ExpenseType.TRANSPORTATION: 1000.0,
                    ExpenseType.ACCOMMODATION: 1000.0,
                    ExpenseType.ENTERTAINMENT: 1500.0,
                },
                EmployeeLevel.SENIOR: {
                    ExpenseType.MEAL: 300.0,
                    ExpenseType.TRANSPORTATION: 2000.0,
                    ExpenseType.ACCOMMODATION: 1500.0,
                    ExpenseType.ENTERTAINMENT: 3000.0,
                },
                EmployeeLevel.MANAGER: {
                    ExpenseType.MEAL: 400.0,
                    ExpenseType.TRANSPORTATION: 3000.0,
                    ExpenseType.ACCOMMODATION: 2500.0,
                    ExpenseType.ENTERTAINMENT: 5000.0,
                },
                EmployeeLevel.DIRECTOR: {
                    ExpenseType.MEAL: 600.0,
                    ExpenseType.TRANSPORTATION: 5000.0,
                    ExpenseType.ACCOMMODATION: 4000.0,
                    ExpenseType.ENTERTAINMENT: 10000.0,
                },
                EmployeeLevel.VP: {
                    ExpenseType.MEAL: 1000.0,
                    ExpenseType.TRANSPORTATION: 10000.0,
                    ExpenseType.ACCOMMODATION: 8000.0,
                    ExpenseType.ENTERTAINMENT: 20000.0,
                },
            },
            "monthly_limits": {
                EmployeeLevel.INTERN: 2000.0,
                EmployeeLevel.JUNIOR: 5000.0,
                EmployeeLevel.MIDDLE: 10000.0,
                EmployeeLevel.SENIOR: 20000.0,
                EmployeeLevel.MANAGER: 50000.0,
                EmployeeLevel.DIRECTOR: 100000.0,
                EmployeeLevel.VP: 500000.0,
            },
        },
        "receipt_required": {
            "rule_id": "R002",
            "rule_name": "发票要求",
            "description": "超过一定金额必须提供发票",
            "threshold": 200.0,
        },
        "meal_per_day_limit": {
            "rule_id": "R003",
            "rule_name": "每日餐费上限",
            "description": "单日餐费报销总额不得超过上限",
            "limits": {
                EmployeeLevel.INTERN: 150.0,
                EmployeeLevel.JUNIOR: 250.0,
                EmployeeLevel.MIDDLE: 400.0,
                EmployeeLevel.SENIOR: 600.0,
                EmployeeLevel.MANAGER: 800.0,
                EmployeeLevel.DIRECTOR: 1200.0,
                EmployeeLevel.VP: 2000.0,
            },
        },
        "travel_accommodation_city_tier": {
            "rule_id": "R004",
            "rule_name": "出差住宿城市分级标准",
            "description": "根据出差城市级别设定住宿标准",
            "tier1_cities": ["北京", "上海", "广州", "深圳", "杭州"],
            "tier2_cities": ["成都", "重庆", "武汉", "南京", "西安", "苏州", "天津", "厦门"],
            "multipliers": {
                "tier1": 1.5,
                "tier2": 1.2,
                "tier3": 1.0,
            },
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
                "engineering": 50000.0,
                "sales": 30000.0,
                "marketing": 40000.0,
                "hr": 20000.0,
                "finance": 10000.0,
                "operations": 25000.0,
                "admin": 15000.0,
            },
            "entertainment_monthly": {
                "engineering": 20000.0,
                "sales": 80000.0,
                "marketing": 50000.0,
                "hr": 10000.0,
                "finance": 5000.0,
                "operations": 15000.0,
                "admin": 10000.0,
            },
        },
    },
}


def load_default_rules() -> Dict:
    return DEFAULT_POLICY_RULES


def get_amount_limit(rules: Dict, level: EmployeeLevel, expense_type: ExpenseType) -> Optional[float]:
    limits = (
        rules.get("rules", {})
        .get("amount_limits", {})
        .get("per_transaction_limits", {})
        .get(level, {})
    )
    return limits.get(expense_type)


def get_monthly_limit(rules: Dict, level: EmployeeLevel) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("amount_limits", {})
        .get("monthly_limits", {})
        .get(level)
    )


def get_meal_daily_limit(rules: Dict, level: EmployeeLevel) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("meal_per_day_limit", {})
        .get("limits", {})
        .get(level)
    )


def get_city_tier_multiplier(rules: Dict, city: Optional[str]) -> float:
    if not city:
        return 1.0
    city_rules = rules.get("rules", {}).get("travel_accommodation_city_tier", {})
    multipliers = city_rules.get("multipliers", {"tier1": 1.5, "tier2": 1.2, "tier3": 1.0})
    if city in city_rules.get("tier1_cities", []):
        return multipliers["tier1"]
    elif city in city_rules.get("tier2_cities", []):
        return multipliers["tier2"]
    return multipliers["tier3"]


def get_department_training_quota(rules: Dict, department: str) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("department_quotas", {})
        .get("training_monthly", {})
        .get(department.lower())
    )


def get_department_entertainment_quota(rules: Dict, department: str) -> Optional[float]:
    return (
        rules.get("rules", {})
        .get("department_quotas", {})
        .get("entertainment_monthly", {})
        .get(department.lower())
    )
