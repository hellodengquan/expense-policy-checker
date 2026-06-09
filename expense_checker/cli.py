from __future__ import annotations

import csv
import json
import os
import uuid
import datetime as _dt
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import (
    Department,
    Employee,
    EmployeeLevel,
    ExpenseItem,
    ExpenseType,
    ReimbursementRequest,
    ViolationSeverity,
)
from .policy_engine import PolicyEngine
from .policy_rules import (
    get_amount_limit,
    get_meal_daily_limit,
    get_monthly_limit,
    load_default_rules,
)

app = typer.Typer(
    name="expense-checker",
    help="财务报销规则检查 CLI 工具 - 报销单录入、政策校验、违规汇总",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
engine = PolicyEngine(load_default_rules())

DATA_DIR = Path(os.environ.get("EXPENSE_DATA_DIR", Path.home() / ".expense_checker"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
REQUESTS_FILE = DATA_DIR / "requests.json"
EMPLOYEES_FILE = DATA_DIR / "employees.json"


def _load_employees() -> dict:
    if EMPLOYEES_FILE.exists():
        with open(EMPLOYEES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_employees(data: dict) -> None:
    with open(EMPLOYEES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_requests() -> dict:
    if REQUESTS_FILE.exists():
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_requests(data: dict) -> None:
    with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _employee_to_dict(emp: Employee) -> dict:
    d = emp.model_dump()
    d["join_date"] = emp.join_date.isoformat()
    return d


def _employee_from_dict(d: dict) -> Employee:
    return Employee(
        id=d["id"],
        name=d["name"],
        level=EmployeeLevel(d["level"]),
        department=Department(d["department"]),
        join_date=_dt.date.fromisoformat(d["join_date"]),
    )


def _request_to_dict(req: ReimbursementRequest) -> dict:
    d = req.model_dump()
    d["submit_date"] = req.submit_date.isoformat()
    d["employee"] = _employee_to_dict(req.employee)
    for item, item_dict in zip(req.items, d["items"]):
        item_dict["date"] = item.date.isoformat()
    return d


def _request_from_dict(d: dict) -> ReimbursementRequest:
    employee = _employee_from_dict(d["employee"])
    items = [
        ExpenseItem(
            id=i["id"],
            type=ExpenseType(i["type"]),
            amount=i["amount"],
            date=_dt.date.fromisoformat(i["date"]),
            description=i.get("description", ""),
            city=i.get("city"),
            receipt_provided=i.get("receipt_provided", True),
            participants=i.get("participants"),
        )
        for i in d["items"]
    ]
    return ReimbursementRequest(
        id=d["id"],
        employee=employee,
        items=items,
        submit_date=_dt.date.fromisoformat(d.get("submit_date", _dt.date.today().isoformat())),
        purpose=d.get("purpose", ""),
        project_code=d.get("project_code"),
    )


def _print_request_summary(req: ReimbursementRequest, title: str = "报销单信息") -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("字段", style="bold")
    table.add_column("内容")
    table.add_row("报销单编号", req.id)
    table.add_row("提交日期", req.submit_date.isoformat())
    table.add_row("报销人", f"{req.employee.name}（{req.employee.id}）")
    table.add_row("职级/部门", f"{req.employee.level.value} / {req.employee.department.value}")
    table.add_row("司龄", f"{req.employee.years_of_service} 年")
    table.add_row("费用明细数", str(req.item_count))
    table.add_row("报销总额", f"¥{req.total_amount:,.2f}")
    if req.purpose:
        table.add_row("报销事由", req.purpose)
    if req.project_code:
        table.add_row("项目编号", req.project_code)
    console.print(table)

    if req.items:
        items_table = Table(show_header=True, header_style="bold magenta", title="费用明细")
        items_table.add_column("ID")
        items_table.add_column("类型")
        items_table.add_column("日期")
        items_table.add_column("城市")
        items_table.add_column("金额", justify="right")
        items_table.add_column("发票")
        items_table.add_column("说明")
        for item in req.items:
            items_table.add_row(
                item.id,
                item.type.value,
                item.date.isoformat(),
                item.city or "-",
                f"¥{item.amount:,.2f}",
                "✓" if item.receipt_provided else "✗",
                item.description or "-",
            )
        console.print(items_table)


def _print_check_result(req: ReimbursementRequest, result) -> None:
    status = "合规" if result.is_compliant else "不合规"
    style = "bold green" if result.is_compliant else "bold red"
    title = Text(f"规则校验结果：{status}", style=style)
    console.print(Panel(title, border_style="blue"))

    summary = Table(show_header=False, box=None)
    summary.add_column("项目", style="bold")
    summary.add_column("数值")
    summary.add_row("报销总额", f"¥{result.total_amount:,.2f}")
    summary.add_row("可报销金额", f"[green]¥{result.compliant_amount:,.2f}[/green]")
    diff = result.total_amount - result.compliant_amount
    if diff > 0:
        summary.add_row("不予报销", f"[red]¥{diff:,.2f}[/red]")
    summary.add_row("违规项数", str(result.violation_count))
    summary.add_row("校验时间", result.checked_at.strftime("%Y-%m-%d %H:%M:%S"))
    console.print(summary)

    if result.violations:
        console.print("\n[bold underline red]违规详情汇总：[/bold underline red]\n")
        for idx, v in enumerate(result.violations, 1):
            sev_color = {
                ViolationSeverity.WARNING: "yellow",
                ViolationSeverity.ERROR: "red",
                ViolationSeverity.CRITICAL: "bold red",
            }[v.severity]
            sev_label = {
                ViolationSeverity.WARNING: "警告",
                ViolationSeverity.ERROR: "错误",
                ViolationSeverity.CRITICAL: "严重",
            }[v.severity]
            title = (
                f"[{idx}] [{v.rule_id}] {v.rule_name}  "
                f"[{sev_color}]{sev_label}[/{sev_color}]"
            )
            content = f"  说明：{v.message}\n"
            if v.expense_item_id:
                content += f"  关联明细：{v.expense_item_id}\n"
            if v.overage_amount:
                content += f"  涉及金额：¥{v.overage_amount:,.2f}\n"
            if v.suggestion:
                content += f"  [cyan]建议：{v.suggestion}[/cyan]"
            console.print(Panel(content, title=title, border_style=sev_color, title_align="left"))


def _prompt_with_default(prompt_text: str, default=None, show_default=True, choices=None):
    if choices:
        choice_str = "/".join(str(c.value if hasattr(c, "value") else c) for c in choices)
        full_prompt = f"{prompt_text} ({choice_str})"
    else:
        full_prompt = prompt_text
    return typer.prompt(full_prompt, default=default, show_default=show_default)


@app.command("employee-add", help="添加员工信息")
def employee_add(
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", "-i", help="交互式输入"),
    emp_id: str = typer.Option(None, "--id", help="员工编号"),
    name: str = typer.Option(None, "--name", help="员工姓名"),
    level: str = typer.Option(None, "--level", help=f"职级: {', '.join(l.value for l in EmployeeLevel)}"),
    department: str = typer.Option(None, "--department", help=f"部门: {', '.join(d.value for d in Department)}"),
    join_date_str: str = typer.Option(None, "--join-date", help="入职日期 YYYY-MM-DD"),
):
    if interactive and not all([emp_id, name, level, department, join_date_str]):
        console.print("[bold]📝 新增员工[/bold]")
        emp_id = emp_id or _prompt_with_default("员工编号")
        name = name or _prompt_with_default("员工姓名")
        level = level or _prompt_with_default("职级", choices=list(EmployeeLevel))
        department = department or _prompt_with_default("部门", choices=list(Department))
        join_date_str = join_date_str or _prompt_with_default(
            "入职日期", default=_dt.date.today().isoformat()
        )

    if not all([emp_id, name, level, department, join_date_str]):
        console.print("[red]错误：缺少必要字段[/red]")
        raise typer.Exit(code=1)

    try:
        emp = Employee(
            id=emp_id,
            name=name,
            level=EmployeeLevel(level),
            department=Department(department),
            join_date=_dt.date.fromisoformat(join_date_str),
        )
    except (ValueError, KeyError) as e:
        console.print(f"[red]输入错误：{e}[/red]")
        raise typer.Exit(code=1)

    employees = _load_employees()
    if emp.id in employees:
        if not typer.confirm(f"员工 {emp.id} 已存在，是否覆盖？", default=False):
            raise typer.Exit(code=0)
    employees[emp.id] = _employee_to_dict(emp)
    _save_employees(employees)
    console.print(f"[green]✓ 员工 {emp.name}（{emp.id}）已保存[/green]")


@app.command("employee-list", help="查看员工列表")
def employee_list():
    employees = _load_employees()
    if not employees:
        console.print("[yellow]暂无员工信息，使用 employee-add 添加[/yellow]")
        return

    table = Table(title="员工列表", show_header=True, header_style="bold cyan")
    table.add_column("编号")
    table.add_column("姓名")
    table.add_column("职级")
    table.add_column("部门")
    table.add_column("入职日期")
    table.add_column("司龄(年)")
    for eid, edata in sorted(employees.items()):
        emp = _employee_from_dict(edata)
        table.add_row(
            emp.id,
            emp.name,
            emp.level.value,
            emp.department.value,
            emp.join_date.isoformat(),
            f"{emp.years_of_service}",
        )
    console.print(table)


@app.command("rules", help="查看报销政策规则")
def show_rules(
    table: bool = typer.Option(True, "--table/--no-table", help="显示金额标准表"),
    detail: bool = typer.Option(False, "--detail", "-d", help="显示详细规则说明"),
):
    rules = engine.rules
    title = f"📋 {rules.get('name', '报销政策')} (v{rules.get('version', '')})"
    console.print(Panel(title, border_style="green"))

    if table:
        console.print("\n[bold]各级别费用标准（单笔上限）：[/bold]")
        console.print(engine.get_level_amount_table())

    if detail:
        console.print("\n[bold]规则详情：[/bold]")
        for item in engine.get_rule_summary():
            console.print(
                f"  [{item['rule_id']}] {item['rule_name']}\n"
                f"      {item['description']}\n"
            )


@app.command("hints", help="报销辅助提示 - 根据职级查看标准")
def hints(
    level: str = typer.Option(..., "--level", "-l", help=f"职级: {', '.join(l.value for l in EmployeeLevel)}"),
    city: Optional[str] = typer.Option(None, "--city", "-c", help="出差城市，用于计算住宿标准"),
):
    try:
        emp_level = EmployeeLevel(level)
    except ValueError:
        console.print(f"[red]无效职级：{level}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold green]💡 {emp_level.value} 职级报销标准提示[/bold green]\n")

    tip_table = Table(show_header=True, header_style="bold cyan")
    tip_table.add_column("费用类型", style="bold")
    tip_table.add_column("单笔上限", justify="right")
    tip_table.add_column("每日上限", justify="right")
    tip_table.add_column("备注")

    for etype in [ExpenseType.MEAL, ExpenseType.TRANSPORTATION, ExpenseType.ACCOMMODATION, ExpenseType.ENTERTAINMENT]:
        limit = get_amount_limit(engine.rules, emp_level, etype) or 0
        daily = ""
        note = ""
        if etype == ExpenseType.MEAL:
            daily = f"¥{get_meal_daily_limit(engine.rules, emp_level) or 0:,.0f}"
            note = "单日合计不超上限"
        elif etype == ExpenseType.ACCOMMODATION and city:
            from .policy_rules import get_city_tier_multiplier
            mult = get_city_tier_multiplier(engine.rules, city)
            adjusted = round(limit * mult, 0)
            note = f"{city}: ¥{adjusted:,.0f}（x{mult}）"
        elif etype == ExpenseType.ENTERTAINMENT:
            note = "需≥2人+详细说明"
        tip_table.add_row(
            etype.value,
            f"¥{limit:,.0f}" if limit else "不限",
            daily,
            note,
        )
    console.print(tip_table)

    monthly = get_monthly_limit(engine.rules, emp_level) or 0
    console.print(f"\n  📊 月度报销总额上限：[bold]¥{monthly:,.0f}[/bold]")
    console.print("  🧾 ≥¥200 需提供发票")
    console.print("  📅 费用需在 90 天内报销")


@app.command("add", help="录入报销单（交互式或命令行参数）")
def add_request(
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", "-i", help="交互式录入"),
    employee_id: str = typer.Option(None, "--employee-id", "-e", help="员工编号（需先用 employee-add 添加）"),
    purpose: str = typer.Option("", "--purpose", "-p", help="报销事由"),
    project_code: Optional[str] = typer.Option(None, "--project", help="项目编号"),
    submit_date_str: str = typer.Option(None, "--submit-date", help="提交日期 YYYY-MM-DD"),
    auto_check: bool = typer.Option(True, "--check/--no-check", help="录入后自动校验"),
):
    employees = _load_employees()
    if interactive:
        console.print(Panel("📝 报销单录入向导", border_style="blue"))

        if not employees:
            console.print("[yellow]暂无员工信息，请先使用 employee-add 添加员工[/yellow]")
            if typer.confirm("是否现在添加？", default=True):
                employee_add()
                employees = _load_employees()

        if employees and not employee_id:
            console.print("\n可选员工：")
            for eid, edata in employees.items():
                console.print(f"  {eid}: {edata['name']} ({edata['level']}/{edata['department']})")
            employee_id = _prompt_with_default("\n选择员工编号")

        if employee_id not in employees:
            console.print(f"[red]员工 {employee_id} 不存在[/red]")
            raise typer.Exit(code=1)

        employee = _employee_from_dict(employees[employee_id])
        console.print(f"\n已选择：{employee.name}（{employee.level.value}，{employee.department.value}）")

        hints(level=employee.level.value)

        purpose = purpose or _prompt_with_default("报销事由", default=purpose or "日常办公")
        project_code = project_code or typer.prompt("项目编号（可选）", default="", show_default=False) or None
        submit_date_str = submit_date_str or _prompt_with_default(
            "提交日期", default=_dt.date.today().isoformat()
        )

        items: List[ExpenseItem] = []
        item_index = 1
        while True:
            console.print(f"\n[bold]--- 第 {item_index} 条费用明细 ---[/bold]")
            etype_str = _prompt_with_default("费用类型", choices=list(ExpenseType))
            etype = ExpenseType(etype_str)

            suggested_limit = get_amount_limit(engine.rules, employee.level, etype)
            hint = f"（建议上限 ¥{suggested_limit:.0f}）" if suggested_limit else ""
            while True:
                amount_str = _prompt_with_default(f"金额{hint}", default="0")
                try:
                    amount = float(amount_str)
                    if amount <= 0:
                        console.print("[yellow]金额需大于0[/yellow]")
                        continue
                    break
                except ValueError:
                    console.print("[yellow]请输入有效数字[/yellow]")

            date_str = _prompt_with_default("发生日期", default=_dt.date.today().isoformat())
            description = typer.prompt("费用说明（可选）", default="", show_default=False)

            city = None
            if etype in (ExpenseType.ACCOMMODATION, ExpenseType.TRANSPORTATION):
                city = typer.prompt("发生城市（可选）", default="", show_default=False) or None

            receipt = True
            if amount >= 200:
                receipt = typer.confirm(f"金额 ≥¥200，是否已提供发票？", default=True)
            else:
                receipt = typer.confirm("是否有发票？", default=True)

            participants = None
            if etype == ExpenseType.ENTERTAINMENT:
                p_str = typer.prompt("参与人员（逗号分隔，至少2人）", default="", show_default=False)
                if p_str:
                    participants = [p.strip() for p in p_str.split(",") if p.strip()]

            item = ExpenseItem(
                id=f"ITEM-{uuid.uuid4().hex[:8].upper()}",
                type=etype,
                amount=amount,
                date=_dt.date.fromisoformat(date_str),
                description=description,
                city=city,
                receipt_provided=receipt,
                participants=participants,
            )
            items.append(item)
            item_index += 1

            if not typer.confirm("继续添加明细？", default=False):
                break
    else:
        if not employee_id or employee_id not in employees:
            console.print("[red]需指定有效员工编号[/red]")
            raise typer.Exit(code=1)
        employee = _employee_from_dict(employees[employee_id])
        items = []
        submit_date_str = submit_date_str or _dt.date.today().isoformat()

    if not items:
        console.print("[red]未添加任何费用明细[/red]")
        raise typer.Exit(code=1)

    req = ReimbursementRequest(
        id=f"REX-{_dt.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
        employee=employee,
        items=items,
        submit_date=_dt.date.fromisoformat(submit_date_str),
        purpose=purpose,
        project_code=project_code,
    )

    requests_data = _load_requests()
    requests_data[req.id] = _request_to_dict(req)
    _save_requests(requests_data)

    console.print(f"[green]✓ 报销单已保存：{req.id}[/green]")
    _print_request_summary(req)

    if auto_check:
        result = engine.check(req)
        _print_check_result(req, result)


@app.command("check", help="校验报销单（按编号或全部）")
def check_request(
    request_id: Optional[str] = typer.Argument(None, help="报销单编号，不传则校验全部"),
    summary_only: bool = typer.Option(False, "--summary", "-s", help="仅显示汇总"),
):
    requests_data = _load_requests()
    if not requests_data:
        console.print("[yellow]暂无报销单，使用 add 命令录入[/yellow]")
        return

    if request_id:
        if request_id not in requests_data:
            console.print(f"[red]报销单 {request_id} 不存在[/red]")
            raise typer.Exit(code=1)
        req = _request_from_dict(requests_data[request_id])
        _print_request_summary(req)
        result = engine.check(req)
        _print_check_result(req, result)
        return

    all_results = []
    for rid, rdata in requests_data.items():
        req = _request_from_dict(rdata)
        result = engine.check(req)
        all_results.append((req, result))

    table = Table(title="批量校验汇总", show_header=True, header_style="bold cyan")
    table.add_column("编号")
    table.add_column("报销人")
    table.add_column("总额", justify="right")
    table.add_column("可报", justify="right")
    table.add_column("违规", justify="right")
    table.add_column("状态")
    for req, result in all_results:
        status = "[green]合规[/green]" if result.is_compliant else "[red]不合规[/red]"
        table.add_row(
            req.id,
            req.employee.name,
            f"¥{result.total_amount:,.2f}",
            f"¥{result.compliant_amount:,.2f}",
            str(result.violation_count),
            status,
        )
    console.print(table)

    if not summary_only:
        for req, result in all_results:
            if result.violations:
                console.print(f"\n{'-'*60}")
                _print_check_result(req, result)


@app.command("list", help="查看报销单列表")
def list_requests(
    employee_id: Optional[str] = typer.Option(None, "--employee-id", "-e", help="按员工筛选"),
    show_items: bool = typer.Option(False, "--items", help="显示费用明细"),
):
    requests_data = _load_requests()
    if not requests_data:
        console.print("[yellow]暂无报销单[/yellow]")
        return

    filtered = {}
    for rid, rdata in requests_data.items():
        if not employee_id or rdata["employee"]["id"] == employee_id:
            filtered[rid] = rdata

    if not filtered:
        console.print("[yellow]没有匹配的报销单[/yellow]")
        return

    for rid, rdata in sorted(filtered.items()):
        req = _request_from_dict(rdata)
        _print_request_summary(req, title=f"报销单 {rid}")
        if not show_items:
            continue


@app.command("summary", help="违规原因汇总分析")
def violation_summary(
    by_rule: bool = typer.Option(True, "--by-rule/--no-by-rule", help="按规则统计"),
    by_severity: bool = typer.Option(True, "--by-severity/--no-by-severity", help="按严重程度统计"),
    by_employee: bool = typer.Option(False, "--by-employee", help="按员工统计"),
    export: Optional[Path] = typer.Option(None, "--export", help="导出为 JSON 文件"),
):
    requests_data = _load_requests()
    if not requests_data:
        console.print("[yellow]暂无报销单数据[/yellow]")
        return

    all_results = []
    all_violations = []
    for rdata in requests_data.values():
        req = _request_from_dict(rdata)
        result = engine.check(req)
        all_results.append((req, result))
        all_violations.extend(result.violations)

    total_req = len(all_results)
    compliant_req = sum(1 for _, r in all_results if r.is_compliant)
    total_amount = sum(r.total_amount for _, r in all_results)
    compliant_amount = sum(r.compliant_amount for _, r in all_results)

    console.print(Panel("📊 违规汇总分析", border_style="magenta"))
    overview = Table(show_header=False, box=None)
    overview.add_column("指标", style="bold")
    overview.add_column("数值")
    overview.add_row("报销单总数", str(total_req))
    overview.add_row(
        "合规率",
        f"{compliant_req/total_req*100:.1f}%（{compliant_req}/{total_req}）",
    )
    overview.add_row("申报总额", f"¥{total_amount:,.2f}")
    overview.add_row(
        "合规比例",
        f"{compliant_amount/total_amount*100:.1f}%（¥{compliant_amount:,.2f}）",
    )
    overview.add_row("违规总项数", str(len(all_violations)))
    console.print(overview)

    if by_severity and all_violations:
        console.print("\n[bold]按严重程度：[/bold]")
        sev_count = {}
        sev_amount = {}
        for v in all_violations:
            sev_count[v.severity.value] = sev_count.get(v.severity.value, 0) + 1
            if v.overage_amount:
                sev_amount[v.severity.value] = (
                    sev_amount.get(v.severity.value, 0) + v.overage_amount
                )
        table = Table(show_header=True, header_style="bold")
        table.add_column("严重程度")
        table.add_column("数量", justify="right")
        table.add_column("涉及金额", justify="right")
        for sev in [ViolationSeverity.CRITICAL, ViolationSeverity.ERROR, ViolationSeverity.WARNING]:
            sv = sev.value
            color = {"warning": "yellow", "error": "red", "critical": "bold red"}[sv]
            table.add_row(
                f"[{color}]{sev.value}[/{color}]",
                str(sev_count.get(sv, 0)),
                f"¥{sev_amount.get(sv, 0):,.2f}",
            )
        console.print(table)

    if by_rule and all_violations:
        console.print("\n[bold]按规则类型：[/bold]")
        rule_count = {}
        rule_amount = {}
        for v in all_violations:
            key = f"{v.rule_id} {v.rule_name}"
            rule_count[key] = rule_count.get(key, 0) + 1
            if v.overage_amount:
                rule_amount[key] = rule_amount.get(key, 0) + v.overage_amount
        table = Table(show_header=True, header_style="bold")
        table.add_column("规则")
        table.add_column("次数", justify="right")
        table.add_column("涉及金额", justify="right")
        for key in sorted(rule_count, key=lambda k: -rule_count[k]):
            table.add_row(
                key,
                str(rule_count[key]),
                f"¥{rule_amount.get(key, 0):,.2f}",
            )
        console.print(table)

    if by_employee and all_results:
        console.print("\n[bold]按员工：[/bold]")
        emp_stats = {}
        for req, result in all_results:
            eid = req.employee.id
            if eid not in emp_stats:
                emp_stats[eid] = {
                    "name": req.employee.name,
                    "count": 0,
                    "violations": 0,
                    "amount": 0,
                }
            emp_stats[eid]["count"] += 1
            emp_stats[eid]["violations"] += result.violation_count
            emp_stats[eid]["amount"] += result.total_amount
        table = Table(show_header=True, header_style="bold")
        table.add_column("员工")
        table.add_column("单数", justify="right")
        table.add_column("违规项", justify="right")
        table.add_column("总金额", justify="right")
        for eid in sorted(emp_stats, key=lambda k: -emp_stats[k]["violations"]):
            s = emp_stats[eid]
            table.add_row(
                f"{s['name']}({eid})",
                str(s["count"]),
                str(s["violations"]),
                f"¥{s['amount']:,.2f}",
            )
        console.print(table)

    if export:
        export_data = {
            "generated_at": _dt.datetime.now().isoformat(),
            "total_requests": total_req,
            "compliant_requests": compliant_req,
            "total_amount": total_amount,
            "compliant_amount": compliant_amount,
            "total_violations": len(all_violations),
            "violations": [v.model_dump() for v in all_violations],
        }
        with open(export, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        console.print(f"[green]✓ 已导出到 {export}[/green]")


@app.command("import", help="批量导入报销单（CSV 或 JSON）")
def batch_import(
    file: Path = typer.Argument(..., exists=True, readable=True, help="CSV/JSON 文件路径"),
    format: str = typer.Option("auto", "--format", "-f", help="格式: auto, csv, json"),
    check: bool = typer.Option(True, "--check/--no-check", help="导入后立即校验"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览不保存"),
):
    if format == "auto":
        suffix = file.suffix.lower()
        if suffix == ".csv":
            format = "csv"
        elif suffix == ".json":
            format = "json"
        else:
            console.print(f"[red]无法识别格式：{suffix}[/red]")
            raise typer.Exit(code=1)

    employees = _load_employees()
    imported: List[ReimbursementRequest] = []

    try:
        if format == "json":
            with open(file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            raw_list = raw if isinstance(raw, list) else [raw]
            for d in raw_list:
                if "employee" in d and isinstance(d["employee"], dict):
                    if d["employee"]["id"] not in employees:
                        emp = Employee(
                            id=d["employee"]["id"],
                            name=d["employee"]["name"],
                            level=EmployeeLevel(d["employee"]["level"]),
                            department=Department(d["employee"]["department"]),
                            join_date=_dt.date.fromisoformat(d["employee"]["join_date"]),
                        )
                        employees[emp.id] = _employee_to_dict(emp)
                req = _request_from_dict(d)
                imported.append(req)
        elif format == "csv":
            req_map = {}
            with open(file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rid = row.get("request_id") or f"IMPORT-{uuid.uuid4().hex[:8].upper()}"
                    if rid not in req_map:
                        eid = row["employee_id"]
                        if eid not in employees:
                            console.print(f"[red]员工 {eid} 不存在，跳过该行[/red]")
                            continue
                        emp = _employee_from_dict(employees[eid])
                        req_map[rid] = {
                            "id": rid,
                            "employee": emp,
                            "items": [],
                            "submit_date": _dt.date.fromisoformat(
                                row.get("submit_date") or _dt.date.today().isoformat()
                            ),
                            "purpose": row.get("purpose", ""),
                            "project_code": row.get("project_code") or None,
                        }
                    participants = None
                    if row.get("participants"):
                        participants = [
                            p.strip()
                            for p in row["participants"].split("|")
                            if p.strip()
                        ]
                    item = ExpenseItem(
                        id=row.get("item_id") or f"ITEM-{uuid.uuid4().hex[:8].upper()}",
                        type=ExpenseType(row["type"]),
                        amount=float(row["amount"]),
                        date=_dt.date.fromisoformat(row["date"]),
                        description=row.get("description", ""),
                        city=row.get("city") or None,
                        receipt_provided=row.get("receipt", "true").lower()
                        in ("true", "1", "yes"),
                        participants=participants,
                    )
                    req_map[rid]["items"].append(item)
            for rd in req_map.values():
                if rd["items"]:
                    imported.append(ReimbursementRequest(**rd))
    except Exception as e:
        console.print(f"[red]导入失败：{e}[/red]")
        raise typer.Exit(code=1)

    if not imported:
        console.print("[yellow]未导入任何报销单[/yellow]")
        return

    console.print(f"[green]✓ 成功解析 {len(imported)} 份报销单[/green]")

    if dry_run:
        console.print("[yellow]（dry-run 模式，不保存）[/yellow]")
    else:
        requests_data = _load_requests()
        for req in imported:
            while req.id in requests_data:
                req.id = f"{req.id}-{uuid.uuid4().hex[:4].upper()}"
            requests_data[req.id] = _request_to_dict(req)
        _save_requests(requests_data)
        if not _load_employees():
            _save_employees(employees)
        console.print(f"[green]✓ 已保存到数据文件[/green]")

    if check:
        for req in imported:
            _print_request_summary(req)
            result = engine.check(req)
            _print_check_result(req, result)


@app.command("sample", help="生成示例数据（便于演示）")
def generate_sample(
    count: int = typer.Option(3, "--count", "-n", min=1, max=10, help="生成数量"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
):
    import random

    if seed is not None:
        random.seed(seed)

    first_names = ["张", "李", "王", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
    given_names = ["伟", "芳", "娜", "敏", "静", "强", "磊", "洋", "艳", "勇", "军", "杰", "涛", "明"]
    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "苏州"]
    reasons = ["客户拜访", "项目出差", "培训参会", "季度会议", "团队建设", "市场活动"]

    employees = _load_employees()
    sample_employees = []
    levels = list(EmployeeLevel)
    depts = list(Department)

    for i in range(max(3, count)):
        eid = f"E{1000 + i}"
        if eid not in employees:
            name = random.choice(first_names) + random.choice(given_names) + random.choice(given_names)
            emp = Employee(
                id=eid,
                name=name,
                level=random.choice(levels),
                department=random.choice(depts),
                join_date=_dt.date(
                                    random.randint(2018, 2024),
                                    random.randint(1, 12),
                                    random.randint(1, 28),
                                ),
            )
            employees[eid] = _employee_to_dict(emp)
        sample_employees.append(_employee_from_dict(employees[eid]))
    _save_employees(employees)

    requests_data = _load_requests()
    etypes = list(ExpenseType)
    generated = []

    for i in range(count):
        emp = random.choice(sample_employees)
        item_count = random.randint(2, 6)
        items = []
        for j in range(item_count):
            et = random.choice(etypes)
            base_limits = {
                ExpenseType.MEAL: (30, 500),
                ExpenseType.TRANSPORTATION: (50, 3000),
                ExpenseType.ACCOMMODATION: (200, 6000),
                ExpenseType.ENTERTAINMENT: (100, 8000),
                ExpenseType.OFFICE_SUPPLIES: (50, 2000),
                ExpenseType.TRAINING: (100, 10000),
                ExpenseType.MEDICAL: (100, 3000),
                ExpenseType.OTHER: (50, 1500),
            }
            lo, hi = base_limits.get(et, (50, 1000))
            amount = round(random.uniform(lo, hi), 2)
            d = _dt.date.today() - _dt.timedelta(days=random.randint(0, 120))
            city = None
            if et in (ExpenseType.ACCOMMODATION, ExpenseType.TRANSPORTATION):
                city = random.choice(cities)
            participants = None
            if et == ExpenseType.ENTERTAINMENT:
                np = random.randint(1, 4)
                participants = [
                    random.choice(first_names) + random.choice(given_names)
                    for _ in range(np)
                ]
            items.append(
                ExpenseItem(
                    id=f"ITEM-{uuid.uuid4().hex[:8].upper()}",
                    type=et,
                    amount=amount,
                    date=d,
                    description=f"示例{et.value}-{j + 1}",
                    city=city,
                    receipt_provided=random.random() > 0.15,
                    participants=participants,
                )
            )
        req = ReimbursementRequest(
            id=f"REX-{_dt.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            employee=emp,
            items=items,
            submit_date=_dt.date.today(),
            purpose=random.choice(reasons),
            project_code=f"P{random.randint(100, 999)}" if random.random() > 0.4 else None,
        )
        while req.id in requests_data:
            req.id = f"{req.id}-{uuid.uuid4().hex[:4].upper()}"
        requests_data[req.id] = _request_to_dict(req)
        generated.append(req)
    _save_requests(requests_data)

    console.print(f"[green]✓ 已生成 {len(generated)} 份示例报销单[/green]")
    for req in generated:
        result = engine.check(req)
        status = "合规" if result.is_compliant else f"{result.violation_count}项违规"
        console.print(
            f"  {req.id}: {req.employee.name} {req.employee.level.value} "
            f"¥{req.total_amount:,.2f} → {status}"
        )


if __name__ == "__main__":
    app()
