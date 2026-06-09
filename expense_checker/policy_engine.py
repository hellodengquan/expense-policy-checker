from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Dict, List

from .models import (
    EmployeeLevel,
    ExpenseItem,
    ExpenseType,
    PolicyCheckResult,
    ReimbursementRequest,
    Violation,
    ViolationSeverity,
)
from .policy_rules import (
    get_amount_limit,
    get_city_tier_multiplier,
    get_meal_daily_limit,
    get_monthly_limit,
    load_default_rules,
)


class PolicyEngine:
    def __init__(self, rules: Dict = None):
        self.rules = rules if rules else load_default_rules()

    def check(self, request: ReimbursementRequest) -> PolicyCheckResult:
        violations: List[Violation] = []
        compliant_amount = request.total_amount

        violations.extend(self._check_amount_limits(request))
        violations.extend(self._check_receipt_requirements(request))
        violations.extend(self._check_meal_per_day(request))
        violations.extend(self._check_city_tier_accommodation(request))
        violations.extend(self._check_entertainment_requirements(request))
        violations.extend(self._check_expense_date_validity(request))
        violations.extend(self._check_monthly_total(request))

        for v in violations:
            if v.overage_amount and v.overage_amount > 0:
                compliant_amount -= v.overage_amount

        compliant_amount = max(0.0, round(compliant_amount, 2))

        return PolicyCheckResult(
            request_id=request.id,
            total_amount=request.total_amount,
            compliant_amount=compliant_amount,
            violations=violations,
        )

    def check_batch(self, requests: List[ReimbursementRequest]) -> List[PolicyCheckResult]:
        return [self.check(req) for req in requests]

    def _check_amount_limits(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["amount_limits"]
        rule_id = rule["rule_id"]
        rule_name = rule["rule_name"]

        for item in request.items:
            limit = get_amount_limit(self.rules, request.employee.level, item.type)
            if limit and item.amount > limit:
                overage = round(item.amount - limit, 2)
                violations.append(
                    Violation(
                        rule_id=rule_id,
                        rule_name=rule_name,
                        expense_item_id=item.id,
                        message=(
                            f"{item.type.value} 单笔金额 ¥{item.amount:.2f} 超过"
                            f"{request.employee.level.value}职级上限 ¥{limit:.2f}"
                        ),
                        suggestion=(
                            f"将该笔费用拆分为多笔报销或提交特殊审批，"
                            f"超额 ¥{overage:.2f} 部分将不予报销"
                        ),
                        severity=ViolationSeverity.ERROR,
                        overage_amount=overage,
                    )
                )
        return violations

    def _check_receipt_requirements(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["receipt_required"]
        threshold = rule["threshold"]

        for item in request.items:
            if item.amount >= threshold and not item.receipt_provided:
                violations.append(
                    Violation(
                        rule_id=rule["rule_id"],
                        rule_name=rule["rule_name"],
                        expense_item_id=item.id,
                        message=(
                            f"{item.type.value} 金额 ¥{item.amount:.2f} ≥ ¥{threshold:.2f}"
                            "，必须提供发票"
                        ),
                        suggestion=(
                            "请上传对应发票照片或PDF，财务审核需见票付款"
                        ),
                        severity=ViolationSeverity.CRITICAL,
                        overage_amount=item.amount,
                    )
                )
        return violations

    def _check_meal_per_day(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["meal_per_day_limit"]
        daily_limit = get_meal_daily_limit(self.rules, request.employee.level)
        if not daily_limit:
            return violations

        meals_by_date: Dict[_dt.date, float] = defaultdict(float)
        meal_items_by_date: Dict[_dt.date, List[ExpenseItem]] = defaultdict(list)

        for item in request.items:
            if item.type == ExpenseType.MEAL:
                meals_by_date[item.date] += item.amount
                meal_items_by_date[item.date].append(item)

        for expense_date, total in meals_by_date.items():
            if total > daily_limit:
                overage = round(total - daily_limit, 2)
                item_ids = [i.id for i in meal_items_by_date[expense_date]]
                violations.append(
                    Violation(
                        rule_id=rule["rule_id"],
                        rule_name=rule["rule_name"],
                        expense_item_id=",".join(item_ids),
                        message=(
                            f"{expense_date.isoformat()} 餐费合计 ¥{total:.2f} 超过"
                            f"日上限 ¥{daily_limit:.2f}"
                        ),
                        suggestion=(
                            f"单日餐费超标，建议按出差标准合理安排，"
                            f"超额 ¥{overage:.2f} 部分需提供额外说明"
                        ),
                        severity=ViolationSeverity.WARNING,
                        overage_amount=overage,
                    )
                )
        return violations

    def _check_city_tier_accommodation(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["travel_accommodation_city_tier"]
        base_limit = get_amount_limit(
            self.rules, request.employee.level, ExpenseType.ACCOMMODATION
        )
        if not base_limit:
            return violations

        for item in request.items:
            if item.type == ExpenseType.ACCOMMODATION:
                multiplier = get_city_tier_multiplier(self.rules, item.city)
                adjusted_limit = round(base_limit * multiplier, 2)
                if item.amount > adjusted_limit:
                    overage = round(item.amount - adjusted_limit, 2)
                    tier_label = "一线城市" if multiplier == 1.5 else (
                        "二线城市" if multiplier == 1.2 else "其他城市"
                    )
                    violations.append(
                        Violation(
                            rule_id=rule["rule_id"],
                            rule_name=rule["rule_name"],
                            expense_item_id=item.id,
                            message=(
                                f"住宿地 {item.city or '未指定'}（{tier_label}）标准 ¥{adjusted_limit:.2f}，"
                                f"实际 ¥{item.amount:.2f}"
                            ),
                            suggestion=(
                                f"建议选择符合职级标准的酒店，或申请特殊住宿审批，"
                                f"超额 ¥{overage:.2f}"
                            ),
                            severity=ViolationSeverity.ERROR,
                            overage_amount=overage,
                        )
                    )
        return violations

    def _check_entertainment_requirements(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["entertainment_requirements"]
        min_participants = rule["min_participants"]
        min_desc_length = rule["description_min_length"]

        for item in request.items:
            if item.type == ExpenseType.ENTERTAINMENT:
                issues = []
                if item.participants is None or len(item.participants) < min_participants:
                    issues.append(
                        f"需至少 {min_participants} 人参与，"
                        f"当前 {len(item.participants) if item.participants else 0} 人"
                    )
                if len(item.description) < min_desc_length:
                    issues.append(
                        f"事由说明不足 {min_desc_length} 字，"
                        f"请详细填写招待对象、目的等信息"
                    )
                if issues:
                    violations.append(
                        Violation(
                            rule_id=rule["rule_id"],
                            rule_name=rule["rule_name"],
                            expense_item_id=item.id,
                            message="招待费资料不完整：" + "；".join(issues),
                            suggestion="请补充参与人员名单和详细招待事由说明",
                            severity=ViolationSeverity.ERROR,
                        )
                    )
        return violations

    def _check_expense_date_validity(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["expense_date_validity"]
        max_days = rule["max_days_before_submit"]
        allow_future = rule["future_dates_allowed"]

        earliest_allowed = request.submit_date - _dt.timedelta(days=max_days)

        for item in request.items:
            if item.date > request.submit_date and not allow_future:
                violations.append(
                    Violation(
                        rule_id=rule["rule_id"],
                        rule_name=rule["rule_name"],
                        expense_item_id=item.id,
                        message=(
                            f"费用日期 {item.date.isoformat()} 晚于提交日期 "
                            f"{request.submit_date.isoformat()}"
                        ),
                        suggestion="请检查费用日期是否填写正确，预提费用需走特殊流程",
                        severity=ViolationSeverity.CRITICAL,
                    )
                )
            elif item.date < earliest_allowed:
                days_over = (earliest_allowed - item.date).days
                violations.append(
                    Violation(
                        rule_id=rule["rule_id"],
                        rule_name=rule["rule_name"],
                        expense_item_id=item.id,
                        message=(
                            f"费用日期 {item.date.isoformat()} 距今已超过 {max_days} 天"
                            f"（超时 {days_over} 天）"
                        ),
                        suggestion=(
                            f"超过报销时效，需提交逾期报销审批并说明原因，"
                            f"逾期超过 180 天将不予报销"
                        ),
                        severity=ViolationSeverity.WARNING,
                    )
                )
        return violations

    def _check_monthly_total(self, request: ReimbursementRequest) -> List[Violation]:
        violations = []
        rule = self.rules["rules"]["amount_limits"]
        monthly_limit = get_monthly_limit(self.rules, request.employee.level)
        if not monthly_limit or request.total_amount <= monthly_limit:
            return violations

        overage = round(request.total_amount - monthly_limit, 2)
        violations.append(
            Violation(
                rule_id=rule["rule_id"],
                rule_name="月度报销总额上限",
                expense_item_id=None,
                message=(
                    f"本次报销总额 ¥{request.total_amount:.2f} 超过"
                    f"{request.employee.level.value}职级月度上限 ¥{monthly_limit:.2f}"
                ),
                suggestion=(
                    f"建议分摊到后续月份报销，或申请月度超额审批，"
                    f"超额 ¥{overage:.2f}"
                ),
                severity=ViolationSeverity.WARNING,
                overage_amount=overage,
            )
        )
        return violations

    def get_rule_summary(self) -> List[Dict]:
        summary = []
        for key, rule in self.rules.get("rules", {}).items():
            summary.append(
                {
                    "rule_id": rule.get("rule_id", ""),
                    "rule_name": rule.get("rule_name", key),
                    "description": rule.get("description", ""),
                }
            )
        return summary

    def get_level_amount_table(self) -> str:
        levels = [e for e in EmployeeLevel]
        types = [
            ExpenseType.MEAL,
            ExpenseType.TRANSPORTATION,
            ExpenseType.ACCOMMODATION,
            ExpenseType.ENTERTAINMENT,
        ]
        headers = ["职级"] + [t.value for t in types] + ["月度合计"]
        rows = []
        for level in levels:
            row = [level.value]
            for t in types:
                limit = get_amount_limit(self.rules, level, t) or 0
                row.append(f"¥{limit:,.0f}")
            monthly = get_monthly_limit(self.rules, level) or 0
            row.append(f"¥{monthly:,.0f}")
            rows.append(row)
        col_widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
        fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
        sep = "-+-".join("-" * w for w in col_widths)
        lines = [fmt.format(*headers), sep]
        lines.extend(fmt.format(*r) for r in rows)
        return "\n".join(lines)
