"""LibreOffice recalculation and dynamic QA for the Phase 9 workbook."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("phase8_recalculator", ROOT / "scripts" / "recalculate-phase8.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load Phase 8 recalculation controls")
phase8 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phase8
SPEC.loader.exec_module(phase8)


def phase9_checks(document) -> list[dict[str, object]]:
    return [
        {"check": phase8.cell_value(document, "Checks", f"C{row}"),
         "status": phase8.cell_value(document, "Checks", f"G{row}")}
        for row in range(42, 57)
    ]


def recovery_parity(document) -> list[dict[str, object]]:
    payload = json.loads((ROOT / "data" / "phase9" / "processed" / "WORKBOOK_INPUTS.json").read_text(encoding="utf-8"))
    expected = {
        "going_concern_low": next(r for r in payload["cases"] if r["case_id"] == "P9C-GC-1")["illustrative_bank_allocation"],
        "going_concern_base": next(r for r in payload["cases"] if r["case_id"] == "P9C-GC-2")["illustrative_bank_allocation"],
        "going_concern_high": next(r for r in payload["cases"] if r["case_id"] == "P9C-GC-3")["illustrative_bank_allocation"],
        "asset_low": next(r for r in payload["cases"] if r["case_id"] == "P9C-AR-1")["illustrative_bank_allocation"],
        "asset_base": next(r for r in payload["cases"] if r["case_id"] == "P9C-AR-2")["illustrative_bank_allocation"],
        "asset_high": next(r for r in payload["cases"] if r["case_id"] == "P9C-AR-3")["illustrative_bank_allocation"],
    }
    cells = {
        "going_concern_low": "D28", "going_concern_base": "E28", "going_concern_high": "F28",
        "asset_low": "K33", "asset_base": "M33", "asset_high": "N33",
    }
    return [
        {"metric": key, "workbook": phase8.cell_value(document, "Recovery", address),
         "python": float(expected[key]),
         "status": "PASS" if abs(float(phase8.cell_value(document, "Recovery", address)) - float(expected[key])) <= 0.002 else "FAIL"}
        for key, address in cells.items()
    ]


def dynamic_recovery_tests(document) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []

    def add(name: str, passed: bool, observed: object) -> None:
        results.append({"test": name, "status": "PASS" if passed else "FAIL", "observed": observed})

    def workbook_errors() -> list[str]:
        failures: list[str] = []
        error_tokens = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "#SPILL!", "#CALC!")
        for sheet_name in document.Sheets.ElementNames:
            sheet = document.Sheets.getByName(sheet_name)
            cursor = sheet.createCursor()
            cursor.gotoEndOfUsedArea(True)
            # Formula cells are the relevant error surface. Styled worksheet
            # ranges can be much larger than the populated model and made the
            # prior whole-used-area walk impractically slow.
            formula_ranges = cursor.queryContentCells(16)  # CellFlags.FORMULA
            for range_index in range(formula_ranges.getCount()):
                formula_range = formula_ranges.getByIndex(range_index)
                address = formula_range.RangeAddress
                for row in range(address.StartRow, address.EndRow + 1):
                    for col in range(address.StartColumn, address.EndColumn + 1):
                        cell = sheet.getCellByPosition(col, row)
                        if any(token in str(cell.String) or token in str(cell.Formula) for token in error_tokens):
                            failures.append(f"{sheet_name}!{cell.CellAddress.Column}:{cell.CellAddress.Row}")
        return failures

    phase8.set_cell(document, "Assumptions", "D4", "Base")
    document.calculateAll()
    assumptions = document.Sheets.getByName("Assumptions")
    initial_multiple = assumptions.getCellRangeByName("J32")
    add("J32 initial numeric value", abs(float(initial_multiple.Value) - 4.0) <= 0.001, initial_multiple.Value)
    add("J32 initial visible multiple text", str(initial_multiple.String) == "4.00x", initial_multiple.String)
    format_strings = []
    for address in ("I32", "J32", "K32"):
        cell = assumptions.getCellRangeByName(address)
        format_strings.append(document.NumberFormats.getByKey(cell.NumberFormat).FormatString)
    add("I32:K32 use multiple not percentage formats", all("x" in item.lower() and "%" not in item for item in format_strings), format_strings)
    base_gc = float(phase8.cell_value(document, "Recovery", "E28"))
    base_asset = float(phase8.cell_value(document, "Recovery", "M33"))
    phase8.set_cell(document, "Assumptions", "J32", 4.5)
    document.calculateAll()
    changed_gc = float(phase8.cell_value(document, "Recovery", "E28"))
    add("going-concern multiple changes proceeds", changed_gc > base_gc, changed_gc)
    add("J32 numeric 4.5 displays 4.50x", str(initial_multiple.String) == "4.50x", initial_multiple.String)
    add("input edit creates no workbook errors", not workbook_errors(), workbook_errors())
    phase8.set_cell(document, "Assumptions", "J32", 4)
    phase8.set_cell(document, "Assumptions", "J35", 0.60)
    document.calculateAll()
    changed_asset = float(phase8.cell_value(document, "Recovery", "M33"))
    add("receivables realization changes asset proceeds", changed_asset < base_asset, changed_asset)
    phase8.set_cell(document, "Assumptions", "J35", 0.70)
    phase8.set_cell(document, "Assumptions", "J31", 0)
    document.calculateAll()
    add("zero stressed EBITDA produces zero going-concern proceeds", abs(float(phase8.cell_value(document, "Recovery", "E28"))) <= 0.001, phase8.cell_value(document, "Recovery", "E28"))
    phase8.set_cell(document, "Assumptions", "J31", 130.35588353025128)
    document.calculateAll()
    add("official recovery remains N/D", phase8.cell_value(document, "Recovery", "D45") == "N/D", phase8.cell_value(document, "Recovery", "D45"))
    add("goodwill receives zero recovery credit", abs(float(phase8.cell_value(document, "Recovery", "K26"))) <= 0.001, phase8.cell_value(document, "Recovery", "K26"))
    add("intangibles receive zero recovery credit", abs(float(phase8.cell_value(document, "Recovery", "K27"))) <= 0.001, phase8.cell_value(document, "Recovery", "K27"))
    add("Base case selector remains restored", phase8.cell_value(document, "Assumptions", "D4") == "Base", phase8.cell_value(document, "Assumptions", "D4"))
    add("restored multiple returns Base proceeds", abs(float(phase8.cell_value(document, "Recovery", "E28")) - base_gc) <= 0.002, phase8.cell_value(document, "Recovery", "E28"))
    return results


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"inspect", "dynamic"}:
        raise SystemExit("usage: recalculate-phase9.py inspect|dynamic workbook.xlsx report.json")
    mode, workbook, report = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    profile = Path(tempfile.mkdtemp(prefix="quanex-phase9-lo-profile-"))
    process = None
    document = None
    try:
        process, desktop = phase8.connect_office(profile)
        document = phase8.open_workbook(desktop, workbook)
        document.calculateAll()
        phase8.configure_print(document)
        output: dict[str, object] = {"engine": phase8.ENGINE}
        if mode == "dynamic":
            upstream = phase8.dynamic_tests(document)
            recovery = dynamic_recovery_tests(document)
            tests = upstream["tests"] + recovery
            output.update({"dynamic_status": "PASS" if all(r["status"] == "PASS" for r in tests) else "FAIL", "test_count": len(tests), "tests": tests})
        phase8.set_cell(document, "Assumptions", "D4", "Base")
        document.calculateAll()
        document.store()
        checks = phase8.workbook_checks(document)
        p9checks = phase9_checks(document)
        parity = recovery_parity(document)
        output["final_scenario"] = phase8.cell_value(document, "Assumptions", "D4")
        output["parity"] = phase8.parity(document)
        output["checks"] = checks + p9checks
        output["phase9_checks"] = p9checks
        output["phase9_check_failures"] = sum(r["status"] != "PASS" for r in p9checks)
        output["recovery_parity"] = parity
        output["recovery_parity_failures"] = sum(r["status"] != "PASS" for r in parity)
        report.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"mode": mode, "engine": phase8.ENGINE, "status": output.get("dynamic_status", "PASS")}))
    finally:
        if document is not None:
            document.close(True)
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except Exception:
                process.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
