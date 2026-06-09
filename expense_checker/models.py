from __future__ import annotations

import datetime as _dt
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class EmployeeLevel(str, Enum):
    INTERN = "intern"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"


class ExpenseType(str, Enum):
    TRANSPORTATION = "transportation"
    ACCOMMODATION = "accommodation"
    MEAL = "meal"
    ENTERTAINMENT = "entertainment"
    OFFICE_SUPPLIES = "office_supplies"
    TRAINING = "training"
    MEDICAL = "medical"
    OTHER = "other"


class Department(str, Enum):
    ENGINEERING = "engineering"
    SALES = "sales"
    MARKETING = "marketing"
    HR = "hr"
    FINANCE = "finance"
    OPERATIONS = "operations"
    ADMIN = "admin"


class Employee(BaseModel):
    id: str = Field(..., description="员工编号")
    name: str = Field(..., description="员工姓名")
    level: EmployeeLevel = Field(..., description="职级")
    department: Department = Field(..., description="部门")
    join_date: _dt.date = Field(..., description="入职日期")

    @property
    def years_of_service(self) -> float:
        today = _dt.date.today()
        delta = today - self.join_date
        return round(delta.days / 365.25, 1)


class ExpenseItem(BaseModel):
    id: str = Field(..., description="费用明细编号")
    type: ExpenseType = Field(..., description="费用类型")
    amount: float = Field(..., gt=0, description="金额")
    date: _dt.date = Field(..., description="发生日期")
    description: str = Field("", description="费用说明")
    city: Optional[str] = Field(None, description="发生城市")
    receipt_provided: bool = Field(True, description="是否有发票")
    participants: Optional[List[str]] = Field(None, description="参与人员姓名")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        return round(v, 2)


class ViolationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Violation(BaseModel):
    rule_id: str = Field(..., description="规则ID")
    rule_name: str = Field(..., description="规则名称")
    expense_item_id: Optional[str] = Field(None, description="关联费用明细ID")
    message: str = Field(..., description="违规说明")
    suggestion: str = Field("", description="整改建议")
    severity: ViolationSeverity = Field(ViolationSeverity.ERROR, description="严重程度")
    overage_amount: Optional[float] = Field(None, description="超额金额")


class PolicyCheckResult(BaseModel):
    request_id: str = Field(..., description="报销单编号")
    checked_at: _dt.datetime = Field(default_factory=_dt.datetime.now)
    total_amount: float = Field(..., description="总金额")
    compliant_amount: float = Field(..., description="合规金额")
    violations: List[Violation] = Field(default_factory=list)
    is_compliant: bool = Field(True, description="是否完全合规")
    violation_count: int = Field(0, description="违规项数量")

    def model_post_init(self, __context) -> None:
        self.violation_count = len(self.violations)
        self.is_compliant = self.violation_count == 0


class ReimbursementRequest(BaseModel):
    id: str = Field(..., description="报销单编号")
    employee: Employee = Field(..., description="报销人")
    items: List[ExpenseItem] = Field(..., description="费用明细列表")
    submit_date: _dt.date = Field(default_factory=_dt.date.today, description="提交日期")
    purpose: str = Field("", description="报销事由")
    project_code: Optional[str] = Field(None, description="项目编号")

    @property
    def total_amount(self) -> float:
        return round(sum(item.amount for item in self.items), 2)

    @property
    def item_count(self) -> int:
        return len(self.items)

    def get_items_by_type(self, expense_type: ExpenseType) -> List[ExpenseItem]:
        return [item for item in self.items if item.type == expense_type]
