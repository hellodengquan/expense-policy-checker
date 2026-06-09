import datetime as _dt
from expense_checker.models import (
    Department,
    Employee,
    EmployeeLevel,
    ExpenseItem,
    ExpenseType,
    ReimbursementRequest,
)
from expense_checker.policy_engine import PolicyEngine
from expense_checker.policy_rules import load_default_rules


def test_policy_engine_basic():
    engine = PolicyEngine(load_default_rules())

    emp = Employee(
        id="T001",
        name="测试员工",
        level=EmployeeLevel.MIDDLE,
        department=Department.ENGINEERING,
        join_date=_dt.date(2022, 1, 1),
    )

    items_ok = [
        ExpenseItem(
            id="I1",
            type=ExpenseType.MEAL,
            amount=150.0,
            date=_dt.date.today(),
            description="正常餐费",
            receipt_provided=False,
        ),
        ExpenseItem(
            id="I2",
            type=ExpenseType.TRANSPORTATION,
            amount=500.0,
            date=_dt.date.today(),
            description="正常交通",
            receipt_provided=True,
        ),
    ]
    req_ok = ReimbursementRequest(id="TEST-OK", employee=emp, items=items_ok)
    result = engine.check(req_ok)
    assert result.is_compliant is True, f"应合规，但有 {result.violations}"
    assert result.compliant_amount == req_ok.total_amount
    print("✓ 基本合规测试通过")

    items_bad = [
        ExpenseItem(
            id="B1",
            type=ExpenseType.MEAL,
            amount=500.0,
            date=_dt.date.today(),
            description="超标餐费",
            receipt_provided=False,
        ),
    ]
    req_bad = ReimbursementRequest(id="TEST-BAD", employee=emp, items=items_bad)
    result = engine.check(req_bad)
    assert result.is_compliant is False, "应检出违规"
    rule_ids = [v.rule_id for v in result.violations]
    assert "R001" in rule_ids, "应有金额上限违规"
    assert "R002" in rule_ids, "应有发票违规（≥200无发票）"
    assert result.compliant_amount < result.total_amount
    print("✓ 违规检测测试通过（金额+发票）")


def test_meal_per_day_limit():
    engine = PolicyEngine(load_default_rules())
    emp = Employee(
        id="T002",
        name="测试员工B",
        level=EmployeeLevel.JUNIOR,
        department=Department.SALES,
        join_date=_dt.date(2023, 1, 1),
    )
    d = _dt.date.today()
    items = [
        ExpenseItem(id="M1", type=ExpenseType.MEAL, amount=100.0, date=d),
        ExpenseItem(id="M2", type=ExpenseType.MEAL, amount=90.0, date=d),
        ExpenseItem(id="M3", type=ExpenseType.MEAL, amount=80.0, date=d),
    ]
    req = ReimbursementRequest(id="TEST-MEAL", employee=emp, items=items)
    result = engine.check(req)
    rule_ids = [v.rule_id for v in result.violations]
    assert "R003" in rule_ids, "应有日餐费上限违规"
    print("✓ 每日餐费上限测试通过")


def test_city_tier_accommodation():
    engine = PolicyEngine(load_default_rules())
    emp = Employee(
        id="T003", name="测试C", level=EmployeeLevel.MIDDLE,
        department=Department.ENGINEERING, join_date=_dt.date(2022, 6, 1),
    )
    base_limit = 1000.0
    items = [
        ExpenseItem(
            id="H1", type=ExpenseType.ACCOMMODATION,
            amount=base_limit * 1.6, date=_dt.date.today(), city="北京",
        ),
    ]
    req = ReimbursementRequest(id="TEST-HOTEL", employee=emp, items=items)
    result = engine.check(req)
    rule_ids = [v.rule_id for v in result.violations]
    assert "R004" in rule_ids, "应有城市分级住宿违规"
    print("✓ 城市住宿分级测试通过")


def test_expense_date_validity():
    engine = PolicyEngine(load_default_rules())
    emp = Employee(
        id="T004", name="测试D", level=EmployeeLevel.SENIOR,
        department=Department.MARKETING, join_date=_dt.date(2021, 1, 1),
    )
    items = [
        ExpenseItem(
            id="D1", type=ExpenseType.OFFICE_SUPPLIES, amount=100.0,
            date=_dt.date.today() + _dt.timedelta(days=5),
        ),
        ExpenseItem(
            id="D2", type=ExpenseType.OTHER, amount=50.0,
            date=_dt.date.today() - _dt.timedelta(days=200),
        ),
    ]
    req = ReimbursementRequest(id="TEST-DATE", employee=emp, items=items)
    result = engine.check(req)
    rule_ids = [v.rule_id for v in result.violations]
    assert "R006" in rule_ids, "应有日期时效性违规"
    print("✓ 日期时效性测试通过")


def test_entertainment_requirements():
    engine = PolicyEngine(load_default_rules())
    emp = Employee(
        id="T005", name="测试E", level=EmployeeLevel.MANAGER,
        department=Department.SALES, join_date=_dt.date(2020, 1, 1),
    )
    items = [
        ExpenseItem(
            id="E1", type=ExpenseType.ENTERTAINMENT,
            amount=2000.0, date=_dt.date.today(), description="短",
            participants=["仅一人"],
        ),
    ]
    req = ReimbursementRequest(id="TEST-ENT", employee=emp, items=items)
    result = engine.check(req)
    rule_ids = [v.rule_id for v in result.violations]
    assert "R005" in rule_ids, "应有招待费资料不完整违规"
    print("✓ 招待费特殊要求测试通过")


def test_batch_check():
    engine = PolicyEngine(load_default_rules())
    emp1 = Employee(
        id="TB1", name="员工1", level=EmployeeLevel.JUNIOR,
        department=Department.OPERATIONS, join_date=_dt.date(2024, 1, 1),
    )
    emp2 = Employee(
        id="TB2", name="员工2", level=EmployeeLevel.DIRECTOR,
        department=Department.FINANCE, join_date=_dt.date(2018, 1, 1),
    )
    reqs = [
        ReimbursementRequest(
            id=f"BATCH-{i}",
            employee=emp1 if i % 2 == 0 else emp2,
            items=[
                ExpenseItem(
                    id=f"BI-{i}-1", type=ExpenseType.MEAL,
                    amount=60.0 + i * 50, date=_dt.date.today(),
                ),
            ],
        )
        for i in range(5)
    ]
    results = engine.check_batch(reqs)
    assert len(results) == 5
    assert any(not r.is_compliant for r in results), "批量中应有违规"
    print("✓ 批量校验测试通过")


def test_rules_summary():
    engine = PolicyEngine(load_default_rules())
    summary = engine.get_rule_summary()
    assert len(summary) >= 6
    assert all("rule_id" in r for r in summary)
    table = engine.get_level_amount_table()
    assert "职级" in table and "junior" in table
    print("✓ 规则摘要和标准表测试通过")


if __name__ == "__main__":
    test_policy_engine_basic()
    test_meal_per_day_limit()
    test_city_tier_accommodation()
    test_expense_date_validity()
    test_entertainment_requirements()
    test_batch_check()
    test_rules_summary()
    print("\n🎉 所有单元测试通过！")
