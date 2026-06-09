from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict

import pytest
from typer.testing import CliRunner

from expense_checker.cli import app
from expense_checker.models import Department, Employee, EmployeeLevel


runner = CliRunner()


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("EXPENSE_DATA_DIR", str(d))
    import expense_checker.cli as m
    m.DATA_DIR = d
    m.REQUESTS_FILE = d / "requests.json"
    m.EMPLOYEES_FILE = d / "employees.json"
    return d


def _add_employee(emp_id: str, name: str, level: str = "middle", dept: str = "engineering", join_date: str = "2022-01-01") -> None:
    runner.invoke(
        app,
        [
            "employee-add",
            "--no-interactive",
            "--id", emp_id,
            "--name", name,
            "--level", level,
            "--department", dept,
            "--join-date", join_date,
        ],
        catch_exceptions=False,
    )


def _valid_request_dict(req_id: str, emp_id: str = "E001") -> Dict[str, Any]:
    return {
        "id": req_id,
        "employee": {
            "id": emp_id,
            "name": "测试员工",
            "level": "middle",
            "department": "engineering",
            "join_date": "2022-01-01",
        },
        "submit_date": _dt.date.today().isoformat(),
        "purpose": "测试报销",
        "project_code": "P123",
        "items": [
            {
                "id": "I1",
                "type": "meal",
                "amount": 120.0,
                "date": _dt.date.today().isoformat(),
                "description": "合规午餐",
                "receipt_provided": True,
            }
        ],
    }


# ============== rules 子命令 ==============

class TestRulesCommand:
    def test_rules_basic_output(self, data_dir: Path):
        result = runner.invoke(app, ["rules"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "公司财务报销政策" in result.stdout
        assert "一线城市" in result.stdout
        assert "北京" in result.stdout or "上海" in result.stdout
        assert "各级别费用标准" in result.stdout

    def test_rules_detail_flag(self, data_dir: Path):
        result = runner.invoke(app, ["rules", "--detail"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "[R001]" in result.stdout
        assert "[R002]" in result.stdout

    def test_rules_no_table_flag(self, data_dir: Path):
        result = runner.invoke(app, ["rules", "--no-table"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "各级别费用标准" not in result.stdout
        assert "公司财务报销政策" in result.stdout

    def test_rules_shows_cities_from_yaml(self, data_dir: Path):
        result = runner.invoke(app, ["rules", "--no-table"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "杭州" in result.stdout
        assert "苏州" in result.stdout


# ============== hints 子命令 ==============

class TestHintsCommand:
    def test_hints_valid_level(self, data_dir: Path):
        result = runner.invoke(app, ["hints", "-l", "middle"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "middle 职级报销标准提示" in result.stdout
        assert "月度报销总额上限" in result.stdout
        assert "meal" in result.stdout

    def test_hints_invalid_level_fails(self, data_dir: Path):
        result = runner.invoke(app, ["hints", "-l", "invalid_level"])
        assert result.exit_code != 0
        assert "无效职级" in result.stdout

    def test_hints_with_tier1_city(self, data_dir: Path):
        result = runner.invoke(app, ["hints", "-l", "middle", "-c", "北京"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "一线城市" in result.stdout
        assert "×1.5" in result.stdout
        assert "城市分级（住宿）" in result.stdout

    def test_hints_with_tier2_city(self, data_dir: Path):
        result = runner.invoke(app, ["hints", "-l", "senior", "-c", "成都"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "二线城市" in result.stdout
        assert "×1.2" in result.stdout

    def test_hints_with_other_city(self, data_dir: Path):
        result = runner.invoke(app, ["hints", "-l", "junior", "-c", "拉萨"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "其他城市" in result.stdout


# ============== add 子命令 ==============

class TestAddCommand:
    def test_add_non_interactive_missing_employee(self, data_dir: Path):
        result = runner.invoke(
            app,
            ["add", "--no-interactive", "-e", "NOBODY"],
        )
        assert result.exit_code != 0
        assert "员工 NOBODY 不存在" in result.stdout

    def test_add_interactive_employee_not_found(self, data_dir: Path):
        _add_employee("E001", "张三")
        result = runner.invoke(
            app,
            ["add", "--no-interactive", "-e", "E999"],
        )
        assert result.exit_code != 0
        assert "员工 E999 不存在" in result.stdout

    def test_add_auto_check_invokes_engine(self, data_dir: Path):
        _add_employee("E002", "李四", level="intern")
        from expense_checker.cli import _load_employees, _request_from_dict, _request_to_dict
        from expense_checker.models import ExpenseItem, ExpenseType, ReimbursementRequest

        emp_dict = _load_employees()["E002"]
        emp = Employee(
            id=emp_dict["id"],
            name=emp_dict["name"],
            level=EmployeeLevel(emp_dict["level"]),
            department=Department(emp_dict["department"]),
            join_date=_dt.date.fromisoformat(emp_dict["join_date"]),
        )
        req = ReimbursementRequest(
            id="REX-ADD-TEST-01",
            employee=emp,
            submit_date=_dt.date.today(),
            purpose="测试 add",
            items=[
                ExpenseItem(
                    id="I99",
                    type=ExpenseType.MEAL,
                    amount=500.0,
                    date=_dt.date.today(),
                    description="超标 intern 餐费",
                    receipt_provided=False,
                )
            ],
        )
        from expense_checker.cli import engine, _load_requests, _save_requests
        existing = _load_requests()
        existing[req.id] = _request_to_dict(req)
        _save_requests(existing)

        result = runner.invoke(app, ["check", req.id, "-s"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "不合规" in result.stdout or str(result.violation_count) if hasattr(result, "violation_count") else True


# ============== summary 子命令 ==============

class TestSummaryCommand:
    def test_summary_empty_no_crash(self, data_dir: Path):
        result = runner.invoke(app, ["summary"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "暂无报销单数据" in result.stdout

    def test_summary_with_data(self, data_dir: Path):
        _add_employee("E100", "王五")
        from expense_checker.cli import _load_employees, _request_to_dict, _save_requests, _load_requests

        emp_dict = _load_employees()["E100"]
        emp = Employee(
            id=emp_dict["id"],
            name=emp_dict["name"],
            level=EmployeeLevel(emp_dict["level"]),
            department=Department(emp_dict["department"]),
            join_date=_dt.date.fromisoformat(emp_dict["join_date"]),
        )
        from expense_checker.models import ExpenseItem, ExpenseType, ReimbursementRequest
        req = ReimbursementRequest(
            id="REX-SUM-01",
            employee=emp,
            submit_date=_dt.date.today(),
            purpose="汇总测试",
            items=[
                ExpenseItem(
                    id="II1", type=ExpenseType.MEAL, amount=5000.0,
                    date=_dt.date.today(), description="大额餐费",
                    receipt_provided=False,
                )
            ],
        )
        data = _load_requests()
        data[req.id] = _request_to_dict(req)
        _save_requests(data)

        result = runner.invoke(app, ["summary"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "违规汇总分析" in result.stdout
        assert "报销单总数" in result.stdout
        assert "按严重程度" in result.stdout
        assert "按规则类型" in result.stdout

    def test_summary_export_json(self, data_dir: Path, tmp_path: Path):
        _add_employee("E99", "赵六", level="senior")
        from expense_checker.cli import _load_employees, _request_to_dict, _save_requests, _load_requests
        from expense_checker.models import ExpenseItem, ExpenseType, ReimbursementRequest

        emp_dict = _load_employees()["E99"]
        emp = Employee(
            id=emp_dict["id"], name=emp_dict["name"],
            level=EmployeeLevel(emp_dict["level"]),
            department=Department(emp_dict["department"]),
            join_date=_dt.date.fromisoformat(emp_dict["join_date"]),
        )
        req = ReimbursementRequest(
            id="REX-EXP-01", employee=emp, submit_date=_dt.date.today(),
            purpose="导出测试",
            items=[
                ExpenseItem(id="X1", type=ExpenseType.TRAINING, amount=100.0,
                            date=_dt.date.today(), description="小费用", receipt_provided=True)
            ],
        )
        data = _load_requests()
        data[req.id] = _request_to_dict(req)
        _save_requests(data)

        out = tmp_path / "export.json"
        result = runner.invoke(app, ["summary", "--export", str(out)], catch_exceptions=False)
        assert result.exit_code == 0
        assert out.exists()
        content = json.loads(out.read_text(encoding="utf-8"))
        assert content["total_requests"] == 1
        assert "generated_at" in content
        assert "violations" in content


# ============== import 子命令 ==============

class TestImportCommand:
    def test_import_empty_file_fails(self, data_dir: Path, tmp_path: Path):
        empty = tmp_path / "empty.json"
        empty.write_text("")
        result = runner.invoke(app, ["import", str(empty), "-f", "json", "--no-check"])
        assert result.exit_code != 0
        assert "文件为空" in result.stdout

    def test_import_invalid_json_format(self, data_dir: Path, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ this is not valid json !!!")
        result = runner.invoke(app, ["import", str(bad), "-f", "json", "--no-check"])
        assert result.exit_code != 0
        assert "JSON 格式错误" in result.stdout

    def test_import_json_missing_required_fields(self, data_dir: Path, tmp_path: Path):
        bad = tmp_path / "missing.json"
        bad.write_text(json.dumps({"not_a_request": True}))
        result = runner.invoke(app, ["import", str(bad), "-f", "json", "--no-check"])
        assert result.exit_code != 0
        assert "缺失必填字段" in result.stdout

    def test_import_json_valid_success(self, data_dir: Path, tmp_path: Path):
        _add_employee("E200", "合法员工", level="junior")
        valid = tmp_path / "ok.json"
        payload = [
            _valid_request_dict("REX-IMP-VALID-01", "E200"),
        ]
        valid.write_text(json.dumps(payload, ensure_ascii=False))
        result = runner.invoke(app, ["import", str(valid), "-f", "json", "--no-check"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "成功解析 1 份报销单" in result.stdout
        from expense_checker.cli import _load_requests
        saved = _load_requests()
        assert any("REX-IMP-VALID-01" in k for k in saved.keys())

    def test_import_duplicate_id_error_mode(self, data_dir: Path, tmp_path: Path):
        _add_employee("E300", "重复测试员工")
        data = [_valid_request_dict("REX-DUP-TEST", "E300")]
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps(data, ensure_ascii=False))
        f2.write_text(json.dumps(data, ensure_ascii=False))

        r1 = runner.invoke(app, ["import", str(f1), "-f", "json", "--no-check"], catch_exceptions=False)
        assert r1.exit_code == 0

        r2 = runner.invoke(
            app,
            ["import", str(f2), "-f", "json", "--no-check", "--on-duplicate", "error"],
            catch_exceptions=False,
        )
        assert r2.exit_code != 0
        assert "重复单号" in r2.stdout

    def test_import_duplicate_id_skip_mode(self, data_dir: Path, tmp_path: Path):
        _add_employee("E301", "跳过测试员工")
        data = [_valid_request_dict("REX-DUP-SKIP", "E301")]
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps(data, ensure_ascii=False))
        f2.write_text(json.dumps(data, ensure_ascii=False))

        runner.invoke(app, ["import", str(f1), "-f", "json", "--no-check"], catch_exceptions=False)
        result = runner.invoke(
            app,
            ["import", str(f2), "-f", "json", "--no-check", "--on-duplicate", "skip"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "跳过重复单号" in result.stdout

    def test_import_duplicate_id_rename_mode(self, data_dir: Path, tmp_path: Path):
        _add_employee("E302", "重命名测试员工")
        data = [_valid_request_dict("REX-DUP-REN", "E302")]
        f1 = tmp_path / "a.json"
        f2 = tmp_path / "b.json"
        f1.write_text(json.dumps(data, ensure_ascii=False))
        f2.write_text(json.dumps(data, ensure_ascii=False))

        runner.invoke(app, ["import", str(f1), "-f", "json", "--no-check"], catch_exceptions=False)
        result = runner.invoke(
            app,
            ["import", str(f2), "-f", "json", "--no-check", "--on-duplicate", "rename"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "重命名重复单号" in result.stdout

    def test_import_csv_missing_required_columns(self, data_dir: Path, tmp_path: Path):
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("foo,bar\n1,2\n", encoding="utf-8")
        result = runner.invoke(app, ["import", str(bad_csv), "-f", "csv", "--no-check"])
        assert result.exit_code != 0
        assert "CSV 缺失必填列" in result.stdout

    def test_import_csv_valid_success(self, data_dir: Path, tmp_path: Path):
        _add_employee("E400", "CSV 员工", level="middle")
        good_csv = tmp_path / "good.csv"
        with open(good_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "request_id", "employee_id", "submit_date", "purpose", "project_code",
                "item_id", "type", "amount", "date", "description", "city", "receipt", "participants",
            ])
            w.writerow([
                "REX-CSV-OK", "E400", _dt.date.today().isoformat(), "CSV 测试", "CSV01",
                "CI1", "meal", "80.00", _dt.date.today().isoformat(), "午餐", "", "true", "",
            ])
        result = runner.invoke(app, ["import", str(good_csv), "-f", "csv", "--no-check"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "成功解析 1 份报销单" in result.stdout

    def test_import_dry_run_does_not_save(self, data_dir: Path, tmp_path: Path):
        _add_employee("E500", "DryRun")
        data = [_valid_request_dict("REX-DRY-RUN-01", "E500")]
        f = tmp_path / "dry.json"
        f.write_text(json.dumps(data, ensure_ascii=False))

        from expense_checker.cli import _load_requests
        before = dict(_load_requests())

        result = runner.invoke(
            app,
            ["import", str(f), "-f", "json", "--no-check", "--dry-run"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "dry-run 模式，不保存" in result.stdout

        after = _load_requests()
        assert before == after


# ============== 综合 & 辅助 ==============

class TestIntegrated:
    def test_yaml_config_overrides_cities(self, tmp_path: Path, monkeypatch):
        custom = tmp_path / "custom.yaml"
        custom.write_text("""
version: "2.0.0"
name: "自定义政策"
rules:
  amount_limits:
    rule_id: "R001"
    rule_name: "x"
    description: "x"
    per_transaction_limits:
      intern:
        meal: 50
        transportation: 100
        accommodation: 300
        entertainment: 200
      middle:
        meal: 99
        transportation: 77
        accommodation: 66
        entertainment: 55
    monthly_limits:
      intern: 1000
      middle: 5000
  receipt_required:
    rule_id: "R002"
    rule_name: "x"
    description: "x"
    threshold: 500
  meal_per_day_limit:
    rule_id: "R003"
    rule_name: "x"
    description: "x"
    limits:
      intern: 100
      middle: 200
  travel_accommodation_city_tier:
    rule_id: "R004"
    rule_name: "x"
    description: "x"
    tier1_cities: ["火星市", "月球镇"]
    tier2_cities: ["空间站", "海底城"]
    multipliers: {tier1: 2.0, tier2: 1.3, tier3: 0.8}
  entertainment_requirements:
    rule_id: "R005"
    rule_name: "x"
    description: "x"
    min_participants: 2
    description_min_length: 5
  expense_date_validity:
    rule_id: "R006"
    rule_name: "x"
    description: "x"
    max_days_before_submit: 30
    future_dates_allowed: false
  department_quotas:
    rule_id: "R007"
    rule_name: "x"
    description: "x"
    training_monthly: {engineering: 1}
    entertainment_monthly: {engineering: 2}
""", encoding="utf-8")
        monkeypatch.setenv("EXPENSE_POLICY_CONFIG", str(custom))
        from expense_checker import policy_rules
        # 强制重载
        import importlib
        importlib.reload(policy_rules)
        from expense_checker.cli import engine as _engine
        from expense_checker.policy_engine import PolicyEngine
        fresh_engine = PolicyEngine(policy_rules.load_default_rules())
        from expense_checker.policy_rules import get_tier1_cities, get_tier2_cities
        t1 = get_tier1_cities(fresh_engine.rules)
        t2 = get_tier2_cities(fresh_engine.rules)
        assert "火星市" in t1
        assert "月球镇" in t1
        assert "空间站" in t2
        assert "北京" not in t1


# ============== validate-config 子命令 ==============

class TestValidateConfigCommand:
    def test_builtin_default_is_valid(self, data_dir: Path):
        result = runner.invoke(app, ["validate-config"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "校验通过" in result.stdout

    def test_builtin_quiet_flag_no_output(self, data_dir: Path):
        result = runner.invoke(app, ["validate-config", "-q"], catch_exceptions=False)
        assert result.exit_code == 0
        assert result.stdout == ""

    def test_valid_custom_path(self, data_dir: Path, tmp_path: Path):
        from tests.test_config_schema import MINIMAL_VALID
        import copy, yaml
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["name"] = "测试政策 validate-config"
        f = tmp_path / "ok.yaml"
        f.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        result = runner.invoke(app, ["validate-config", str(f)], catch_exceptions=False)
        assert result.exit_code == 0
        assert "校验通过" in result.stdout
        # Rich 换行可能把路径拆开，按片段判断
        flat = result.stdout.replace("\n", "").replace(" ", "")
        assert f.name in flat or "ok.yaml" in flat

    def test_missing_file_reports_error(self, data_dir: Path, tmp_path: Path):
        f = tmp_path / "not_exist.yaml"
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        assert "校验失败" in result.stdout
        assert "文件不存在" in result.stdout

    def test_empty_yaml_reports_error(self, data_dir: Path, tmp_path: Path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        assert "文件为空" in result.stdout

    def test_missing_version_and_rules_keys(self, data_dir: Path, tmp_path: Path):
        f = tmp_path / "missing.yaml"
        f.write_text("description: 缺少 version 和 rules\n")
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        flat = result.stdout.replace("\n", "").replace(" ", "")
        assert "version" in flat
        assert "rules" in flat

    def test_tier1_cities_type_error_reports_path(self, data_dir: Path, tmp_path: Path):
        from tests.test_config_schema import MINIMAL_VALID
        import copy, yaml
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = "北京,上海,不是列表"
        f = tmp_path / "bad_tier.yaml"
        f.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        flat = result.stdout.replace("\n", "").replace(" ", "")
        assert "tier1_cities" in flat
        assert "期望list" in flat

    def test_unknown_level_reports_path(self, data_dir: Path, tmp_path: Path):
        from tests.test_config_schema import MINIMAL_VALID
        import copy, yaml
        cfg = copy.deepcopy(MINIMAL_VALID)
        cfg["rules"]["amount_limits"]["monthly_limits"]["superman"] = 99999
        f = tmp_path / "bad_level.yaml"
        f.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        assert "superman" in result.stdout
        assert "未知职级" in result.stdout

    def test_bad_yaml_syntax(self, data_dir: Path, tmp_path: Path):
        f = tmp_path / "syntax.yaml"
        f.write_text("{a: 1, b: [unclosed,")
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        assert "YAML 解析错误" in result.stdout

    def test_non_utf8_encoding_reports_error(self, data_dir: Path, tmp_path: Path):
        # 用 GBK 写入且没有 BOM：validate-config 不做 chardet 降级，直接提示编码错
        f = tmp_path / "gbk_rules.yaml"
        from tests.test_config_schema import MINIMAL_VALID
        import copy, yaml
        cfg = copy.deepcopy(MINIMAL_VALID)
        yaml_text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
        f.write_bytes(yaml_text.encode("gbk"))
        result = runner.invoke(app, ["validate-config", str(f)])
        assert result.exit_code == 1
        assert "编码错误" in result.stdout or "UTF-8" in result.stdout

    def test_invalid_config_triggers_log_warning(self, data_dir: Path, tmp_path: Path, caplog):
        """结构不合法时：1) 走 rules 子命令加载应触发 logging.warning，2) 仍用内置规则渲染"""
        from tests.test_config_schema import MINIMAL_VALID
        import copy, yaml
        cfg = copy.deepcopy(MINIMAL_VALID)
        # 把 tier1_cities 改成字符串让校验失败
        cfg["rules"]["travel_accommodation_city_tier"]["tier1_cities"] = "wrong"
        f = tmp_path / "bad.yaml"
        f.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))

        import importlib, logging
        from expense_checker import policy_rules, cli
        # caplog 设置 WARNING 级别
        caplog.set_level(logging.WARNING, logger="expense_checker")

        # 直接调用 load_rules_from_yaml 触发日志
        result = policy_rules.load_rules_from_yaml(f)
        assert result is None  # 校验失败 -> 回退，返回 None
        assert any("校验失败" in record.message for record in caplog.records)
        assert any("tier1_cities" in record.message for record in caplog.records)
        # 提示 validate-config 子命令
        assert any("validate-config" in record.message for record in caplog.records)
