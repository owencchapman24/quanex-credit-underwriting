"""Safe LibreOffice recalculation, capture, inspection and dynamic QA for Phase 8."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


SCENARIOS = (
    ("Base", "BASE"),
    ("Moderate unmitigated", "MODERATE_UNMITIGATED"),
    ("Moderate mitigated", "MODERATE_MITIGATED"),
    ("Severe unmitigated", "SEVERE_UNMITIGATED"),
    ("Severe mitigated", "SEVERE_MITIGATED"),
    ("Moderate Phase 6 analytical shutoff", "MODERATE_NO_WAIVER"),
    ("Severe Phase 6 analytical shutoff", "SEVERE_NO_WAIVER"),
    ("Moderate Phase 7 covenant-linked no-waiver", "MODERATE_PHASE7_COVENANT_NO_WAIVER"),
    ("Severe Phase 7 covenant-linked no-waiver", "SEVERE_PHASE7_COVENANT_NO_WAIVER"),
)
SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
ENGINE = "LibreOffice 26.8.0.3"
# Stable technical-generation label for the bounded post-Phase 11 remediation.
# It is not borrower evidence and prevents repeated builds from changing CSVs.
CAPTURED_AT = "2026-09-13T00:00:00Z"


def prop(name: str, value: object) -> PropertyValue:
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def connect_office(profile: Path):
    port = free_port()
    profile_url = uno.systemPathToFileUrl(str(profile))
    process = subprocess.Popen([
        str(SOFFICE), "--headless", "--nologo", "--nodefault", "--norestore",
        f"-env:UserInstallation={profile_url}",
        f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    context = None
    for _ in range(100):
        try:
            context = resolver.resolve(
                f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
            )
            break
        except Exception:
            time.sleep(0.1)
    if context is None:
        process.terminate()
        raise RuntimeError("Unable to connect to isolated LibreOffice instance")
    desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    return process, desktop


def open_workbook(desktop, path: Path):
    url = uno.systemPathToFileUrl(str(path.resolve()))
    document = desktop.loadComponentFromURL(url, "_blank", 0, (prop("Hidden", True), prop("ReadOnly", False)))
    if document is None:
        raise RuntimeError(f"LibreOffice could not open {path}")
    document.enableAutomaticCalculation(True)
    return document


def cell(document, sheet: str, address: str):
    return document.Sheets.getByName(sheet).getCellRangeByName(address)


def cell_value(document, sheet: str, address: str):
    item = cell(document, sheet, address)
    if getattr(item, "Error", 0):
        return item.String
    if item.Type.value == "VALUE":
        return item.Value
    if item.Type.value == "FORMULA" and item.FormulaResultType.value == "VALUE":
        return item.Value
    return item.String


def set_cell(document, sheet: str, address: str, value: object) -> None:
    item = cell(document, sheet, address)
    if isinstance(value, (int, float)):
        item.Value = float(value)
    else:
        item.String = "" if value is None else str(value)


def configure_print(document) -> None:
    landscape = {"Forecast", "Debt Schedule", "Liquidity", "Covenants", "Scenario Comparison", "Historicals", "Credit Adjustments", "Transaction", "Sensitivities", "Sources"}
    repeated_rows = {
        "Assumptions": (40, 40), "Scenario Comparison": (11, 11), "Historicals": (6, 6),
        "Credit Adjustments": (19, 19), "Forecast": (7, 8), "Debt Schedule": (7, 11),
        "Liquidity": (12, 12), "Covenants": (7, 7), "Sources": (1, 1), "Checks": (6, 6),
    }
    for sheet in document.Sheets:
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(True)
        sheet.setPrintAreas((cursor.RangeAddress,))
        style = document.StyleFamilies.getByName("PageStyles").getByName(sheet.PageStyle)
        style.IsLandscape = sheet.Name in landscape
        # The covenant matrix is intentionally wide; two landscape pages keep
        # decision-facing text legible instead of shrinking 30 fields to one.
        style.ScaleToPagesX = 2 if sheet.Name == "Covenants" else 1
        style.ScaleToPagesY = 0
        style.LeftMargin = 900
        style.RightMargin = 900
        style.TopMargin = 900
        style.BottomMargin = 900
        if sheet.Name in repeated_rows:
            first, last = repeated_rows[sheet.Name]
            title_range = sheet.getCellRangeByPosition(0, first - 1, 0, last - 1)
            sheet.setTitleRows(title_range.RangeAddress)
            sheet.setPrintTitleRows(True)


def capture(document) -> list[dict[str, object]]:
    captures: list[dict[str, object]] = []
    captured_at = CAPTURED_AT
    version = str(cell_value(document, "Assumptions", "D6"))
    source_hash = str(cell_value(document, "Assumptions", "D8"))
    for index, (scenario_name, scenario_id) in enumerate(SCENARIOS, start=12):
        set_cell(document, "Assumptions", "D4", scenario_name)
        document.calculateAll()
        source = document.Sheets.getByName("Scenario Comparison").getCellRangeByName("F5:Y5")
        target = document.Sheets.getByName("Scenario Comparison").getCellRangeByName(f"F{index}:Y{index}")
        values = source.getDataArray()[0]
        target.setDataArray((values,))
        set_cell(document, "Scenario Comparison", f"Z{index}", captured_at)
        set_cell(document, "Scenario Comparison", f"AA{index}", version)
        set_cell(document, "Scenario Comparison", f"AB{index}", source_hash)
        set_cell(document, "Scenario Comparison", f"AC{index}", str(cell_value(document, "Assumptions", "D7")))
        captures.append({
            "capture_id": f"P8C-{index-11:03d}", "scenario_name": scenario_name,
            "scenario_id": scenario_id, "captured_at": captured_at, "source_version": version,
            "source_hash": source_hash, "input_signature": cell_value(document, "Assumptions", "D7"),
            "fy2026_ebitda": values[0], "ebitda_margin": values[1],
            "modeled_operating_cash": values[2], "cfads": values[3],
            "cash_interest": values[4], "scheduled_principal": values[5], "ecf_sweep": values[6],
            "peak_revolver": values[7], "opening_liquidity": values[8],
            "subsequent_minimum_liquidity": values[9], "all_in_minimum_liquidity": values[10],
            "maximum_leverage": values[11], "minimum_coverage": values[12],
            "first_warning": values[13], "first_breach": values[14], "first_draw_shutoff": values[15],
            "first_payment_failure": values[16], "common_horizon_ending_debt": values[17],
            "maturity_gap": values[18], "unpaid_obligations": values[19],
        })
    if cell_value(document, "Assumptions", "D4") != "Base":
        set_cell(document, "Assumptions", "D4", "Base")
    document.calculateAll()
    configure_print(document)
    document.calculateAll()
    document.store()
    return captures


def parity(document) -> dict[str, object]:
    return {
        "fy2024_lender_base_ebitda": cell_value(document, "Credit Adjustments", "D14"),
        "fy2025_lender_base_ebitda": cell_value(document, "Credit Adjustments", "E14"),
        "opening_total_funded_debt": cell_value(document, "Transaction", "D17"),
        "opening_leverage": cell_value(document, "Transaction", "D18"),
        "selected_all_in_liquidity": cell_value(document, "Scenario Comparison", "P12"),
        "selected_common_horizon_debt": cell_value(document, "Scenario Comparison", "W12"),
        "selected_maturity_gap": cell_value(document, "Scenario Comparison", "X12"),
        "moderate_unmitigated_maturity_gap": cell_value(document, "Scenario Comparison", "X13"),
        "moderate_mitigated_maturity_gap": cell_value(document, "Scenario Comparison", "X14"),
        "severe_unmitigated_maturity_gap": cell_value(document, "Scenario Comparison", "X15"),
        "severe_mitigated_maturity_gap": cell_value(document, "Scenario Comparison", "X16"),
        "existing_common_horizon_debt": cell_value(document, "Transaction", "D34"),
        "existing_maturity_gap": cell_value(document, "Transaction", "G34"),
        "reference_maturity_gap": cell_value(document, "Transaction", "G36"),
        "sources_uses_difference": cell_value(document, "Transaction", "D12"),
        "closing_coverage": cell_value(document, "Credit Summary", "D26"),
    }


def workbook_checks(document) -> list[dict[str, object]]:
    return [
        {
            "check": cell_value(document, "Checks", f"C{row}"),
            "status": cell_value(document, "Checks", f"G{row}"),
        }
        for row in range(7, 39)
    ]


def dynamic_tests(document, desktop, workbook: Path) -> tuple[dict[str, object], object]:
    results: list[dict[str, object]] = []

    def reset_document() -> None:
        """Reopen the untouched disposable workbook between independent probes."""
        nonlocal document
        document.close(True)
        document = open_workbook(desktop, workbook)
        document.calculateAll()

    def add(name: str, passed: bool, observed: object) -> None:
        results.append({"test": name, "status": "PASS" if passed else "FAIL", "observed": observed})

    def number(sheet: str, address: str) -> float:
        value = cell_value(document, sheet, address)
        if not isinstance(value, (int, float)):
            raise ValueError(f"{sheet}!{address} is not numeric: {value!r}")
        return float(value)

    def financial_identities() -> dict[str, object]:
        try:
            cash_differences: list[float] = []
            term_differences: list[float] = []
            revolver_differences: list[float] = []
            debt_differences: list[float] = []
            shortfall_differences: list[float] = []
            for row in range(12, 48):
                values = {
                    column: number("Debt Schedule", f"{column}{row}")
                    for column in (
                        "J", "K", "L", "M", "N", "O", "P", "Q", "R", "X", "Y", "Z",
                        "T", "U", "AE", "AF", "AG", "AH", "AI", "AJ", "AP",
                    )
                }
                revolver_before_maturity = values["O"] + values["P"] - values["Q"]
                expected_term = max(
                    0.0,
                    values["J"] - values["K"] - values["L"]
                    - max(0.0, values["M"] - revolver_before_maturity),
                )
                expected_revolver = max(0.0, revolver_before_maturity - values["M"])
                cash_differences.append(abs(values["AP"]))
                term_differences.append(abs(values["N"] - expected_term))
                revolver_differences.append(abs(values["R"] - expected_revolver))
                debt_differences.extend((
                    abs(values["X"] - values["N"] - values["R"]),
                    abs(values["Z"] - values["X"] - values["Y"]),
                ))
                shortfall_differences.extend((
                    abs(values["AF"] - max(0.0, values["AE"] - values["T"])),
                    abs(values["AH"] - max(0.0, values["AG"] - values["K"])),
                    abs(values["AJ"] - max(0.0, values["AI"] - values["U"])),
                ))
            return {
                "max_cash_difference": max(cash_differences),
                "max_term_difference": max(term_differences),
                "max_revolver_difference": max(revolver_differences),
                "max_debt_difference": max(debt_differences),
                "max_shortfall_difference": max(shortfall_differences),
            }
        except (TypeError, ValueError) as exc:
            return {"error": str(exc)}

    def add_identity_test(name: str) -> None:
        observed = financial_identities()
        passed = "error" not in observed and all(float(value) <= 0.000001 for value in observed.values())
        add(name, passed, observed)

    def q2_cfads() -> tuple[float, float, float]:
        forecast = number("Forecast", "D22")
        financing = sum(number("Debt Schedule", f"I{row}") for row in range(12, 15))
        return forecast, financing, financing - forecast

    def add_q2_cfads_test(name: str) -> None:
        observed = q2_cfads()
        add(name, abs(observed[2]) <= 0.000001, observed)

    # Do not write the selector when the saved workbook is already in Base.
    # LibreOffice invalidates the full selected-scenario dependency tree even
    # for a no-op string write, which can make the following independent live
    # input probe surface a spurious Err:522.
    if cell_value(document, "Assumptions", "D4") != "Base":
        set_cell(document, "Assumptions", "D4", "Base")
        document.calculateAll()
    baseline = tuple(cell_value(document, "Scenario Comparison", address) for address in ("F5", "I5", "J5", "L5", "P5", "Q5", "X5"))
    historical = document.Sheets.getByName("Historicals").getCellRangeByName("C7:N50").getDataArray()
    add_identity_test("Base period cash and debt identities reconcile")
    add_q2_cfads_test("Base Forecast and financing Q2 CFADS reconcile")
    for row, label in ((9, "April 2026"), (10, "July 2026")):
        observed = tuple(cell_value(document, "Covenants", f"{column}{row}") for column in ("G", "I", "L", "V", "X"))
        add(
            f"incomplete {label} LTM is N/D",
            observed[:4] == ("N/D", "N/D", "N/D", "N/D") and observed[4] == "INCOMPLETE",
            observed,
        )
    first_complete_leverage = tuple(cell_value(document, "Covenants", address) for address in ("G11", "I11", "L11"))
    add(
        "first complete EBITDA LTM calculates",
        isinstance(first_complete_leverage[0], float) and first_complete_leverage[1] not in {"N/D", "N/M"} and first_complete_leverage[2] in {"COMPLIANT", "WARNING", "BREACH"},
        first_complete_leverage,
    )
    first_complete_all = tuple(cell_value(document, "Covenants", address) for address in ("I12", "O12", "V12", "X12"))
    add(
        "first fully complete leverage and coverage test calculates",
        all(value not in {"N/D", "N/M"} for value in first_complete_all[:3]) and first_complete_all[3] == "COMPLETE",
        first_complete_all,
    )

    base_amort = float(cell_value(document, "Assumptions", "D18")); base_gap = float(cell_value(document, "Scenario Comparison", "X5"))
    base_april_scheduled = number("Debt Schedule", "K14")
    set_cell(document, "Assumptions", "D18", base_amort + 0.025); document.calculateAll()
    add("amortization changes maturity gap", float(cell_value(document, "Scenario Comparison", "X5")) < base_gap, cell_value(document, "Scenario Comparison", "X5"))
    add("April 2026 amortization changes scheduled payment", number("Debt Schedule", "K14") > base_april_scheduled, cell_value(document, "Debt Schedule", "K14"))
    add_identity_test("Amortization probe period identities reconcile")
    reset_document()

    base_term = float(cell_value(document, "Assumptions", "D12")); set_cell(document, "Assumptions", "D12", base_term + 5); document.calculateAll()
    add("term amount changes opening term", abs(float(cell_value(document, "Debt Schedule", "J12")) - (base_term + 5)) < 0.001, cell_value(document, "Debt Schedule", "J12"))
    add_identity_test("Term-size probe period identities reconcile")
    reset_document()
    base_contribution = float(cell_value(document, "Assumptions", "D13")); base_debt = float(cell_value(document, "Transaction", "D17"))
    set_cell(document, "Assumptions", "D13", base_contribution + 5); document.calculateAll()
    add("non-debt contribution reduces opening debt", float(cell_value(document, "Transaction", "D17")) < base_debt, cell_value(document, "Transaction", "D17"))
    add_identity_test("Contribution probe period identities reconcile")
    reset_document()

    base_spread = float(cell_value(document, "Assumptions", "D20")); base_interest = float(cell_value(document, "Scenario Comparison", "J5"))
    base_interest_due = sum(number("Debt Schedule", f"AE{row}") for row in range(12, 48))
    set_cell(document, "Assumptions", "D20", base_spread + 0.01); document.calculateAll()
    add("interest spread changes cash interest", float(cell_value(document, "Scenario Comparison", "J5")) > base_interest, cell_value(document, "Scenario Comparison", "J5"))
    spread_interest_due = sum(number("Debt Schedule", f"AE{row}") for row in range(12, 48))
    add("interest spread changes interest due", spread_interest_due > base_interest_due, spread_interest_due)
    add("February 2026 spread probe cash identity reconciles", abs(number("Debt Schedule", "AP12")) <= 0.000001, cell_value(document, "Debt Schedule", "AP12"))
    add("April 2026 spread probe cash identity reconciles", abs(number("Debt Schedule", "AP14")) <= 0.000001, cell_value(document, "Debt Schedule", "AP14"))
    add_identity_test("Spread probe period identities reconcile")
    reset_document()
    set_cell(document, "Assumptions", "D21", -0.10); document.calculateAll()
    add("EBITDA overlay changes EBITDA", float(cell_value(document, "Scenario Comparison", "F5")) < baseline[0], cell_value(document, "Scenario Comparison", "F5"))
    add_q2_cfads_test("EBITDA overlay flows through financing Q2 CFADS")
    add_identity_test("EBITDA overlay period identities reconcile")
    reset_document()
    set_cell(document, "Assumptions", "D23", 5); document.calculateAll()
    add("DSO change reduces CFADS", float(cell_value(document, "Scenario Comparison", "I5")) < baseline[1], cell_value(document, "Scenario Comparison", "I5"))
    add_q2_cfads_test("DSO overlay flows through financing Q2 CFADS")
    add_identity_test("DSO overlay period identities reconcile")
    reset_document()

    set_cell(document, "Assumptions", "D18", 0.10)
    set_cell(document, "Assumptions", "D20", 0.01)
    set_cell(document, "Assumptions", "D21", -0.10)
    set_cell(document, "Assumptions", "D23", 10)
    document.calculateAll()
    add_q2_cfads_test("Combined rate amortization EBITDA and DSO probe reconciles Q2 CFADS")
    add_identity_test("Combined rate amortization EBITDA and DSO period identities reconcile")
    combined = (
        number("Scenario Comparison", "X5"), number("Scenario Comparison", "P5"),
        number("Scenario Comparison", "J5"),
    )
    add(
        "Combined adverse controls worsen financing outputs",
        combined[0] > float(baseline[6]) or combined[1] < float(baseline[4]) or combined[2] > float(baseline[2]),
        combined,
    )
    reset_document()

    opening_debt = float(cell_value(document, "Transaction", "D17"))
    exact_adjustment = opening_debt / (3.5 * 225.344) - 1
    set_cell(document, "Assumptions", "D21", exact_adjustment); document.calculateAll()
    add("exact leverage boundary is not breach", cell_value(document, "Covenants", "L8") != "BREACH", cell_value(document, "Covenants", "L8"))
    set_cell(document, "Assumptions", "D21", exact_adjustment - 0.0001); document.calculateAll()
    add("above leverage boundary breaches", cell_value(document, "Covenants", "L8") == "BREACH", cell_value(document, "Covenants", "L8"))
    reset_document()

    coverage_warning = number("Assumptions", "D33")
    liquidity_warning = number("Assumptions", "D34")
    add(
        "approved coverage and liquidity warning boundaries retained",
        abs(coverage_warning - 3.5) <= 0.000001 and abs(liquidity_warning - 75.0) <= 0.000001,
        (coverage_warning, liquidity_warning),
    )
    coverage_measure = number("Covenants", "N12")
    set_cell(document, "Assumptions", "D33", coverage_measure - 0.0001); document.calculateAll()
    add("coverage just above warning boundary is compliant", cell_value(document, "Covenants", "R12") == "COMPLIANT", cell_value(document, "Covenants", "R12"))
    set_cell(document, "Assumptions", "D33", coverage_measure); document.calculateAll()
    add("coverage at warning boundary is warning", cell_value(document, "Covenants", "R12") == "WARNING", cell_value(document, "Covenants", "R12"))
    set_cell(document, "Assumptions", "D33", coverage_measure + 0.0001); document.calculateAll()
    add("coverage just below warning boundary is warning", cell_value(document, "Covenants", "R12") == "WARNING", cell_value(document, "Covenants", "R12"))
    set_cell(document, "Assumptions", "D33", coverage_warning); document.calculateAll()

    liquidity_measure = number("Liquidity", "P13")
    set_cell(document, "Assumptions", "D34", liquidity_measure - 0.0001); document.calculateAll()
    add("liquidity just above warning boundary is compliant", cell_value(document, "Liquidity", "R13") == "COMPLIANT", cell_value(document, "Liquidity", "R13"))
    set_cell(document, "Assumptions", "D34", liquidity_measure); document.calculateAll()
    add("liquidity at warning boundary is warning", cell_value(document, "Liquidity", "R13") == "WARNING", cell_value(document, "Liquidity", "R13"))
    set_cell(document, "Assumptions", "D34", liquidity_measure + 0.0001); document.calculateAll()
    add("liquidity just below warning boundary is warning", cell_value(document, "Liquidity", "R13") == "WARNING", cell_value(document, "Liquidity", "R13"))
    set_cell(document, "Assumptions", "D34", liquidity_warning); document.calculateAll()

    set_cell(document, "Assumptions", "D21", -1); document.calculateAll()
    zero_complete = tuple(cell_value(document, "Covenants", address) for address in ("I12", "O12", "V12", "X12"))
    add("zero EBITDA with complete inputs is N/M", zero_complete == ("N/M", "N/M", "N/M", "COMPLETE"), zero_complete)
    reset_document()
    set_cell(document, "Assumptions", "D21", -2); document.calculateAll()
    negative_complete = tuple(cell_value(document, "Covenants", address) for address in ("I12", "O12", "V12", "X12"))
    add("negative EBITDA with complete inputs is N/M", negative_complete == ("N/M", "N/M", "N/M", "COMPLETE"), negative_complete)
    reset_document()

    base_rate = float(cell_value(document, "Assumptions", "D19")); set_cell(document, "Assumptions", "D19", ""); document.calculateAll()
    missing_interest = tuple(cell_value(document, "Covenants", address) for address in ("O12", "R12", "V12", "X12"))
    add("missing due-or-payable interest is N/D", missing_interest == ("N/D", "N/D", "N/D", "INCOMPLETE"), missing_interest)
    reset_document()
    set_cell(document, "Assumptions", "D19", 0); document.calculateAll()
    add("zero due-or-payable interest is N/M", cell_value(document, "Covenants", "O12") == "N/M", cell_value(document, "Covenants", "O12"))
    reset_document()
    set_cell(document, "Assumptions", "D19", -0.01); document.calculateAll()
    add("negative due-or-payable interest is N/M", cell_value(document, "Covenants", "O12") == "N/M", cell_value(document, "Covenants", "O12"))
    reset_document()

    set_cell(document, "Assumptions", "D25", -500); document.calculateAll()
    add("liquidity overlay can exhaust revolver", float(cell_value(document, "Scenario Comparison", "P5")) <= 0.001, cell_value(document, "Scenario Comparison", "P5"))
    tight_shortfall = sum(
        number("Debt Schedule", f"{column}{row}")
        for row in range(12, 48) for column in ("AF", "AH", "AJ")
    )
    add("tight-liquidity case preserves due versus paid shortfalls", tight_shortfall > 0.001, tight_shortfall)
    add_identity_test("Tight-liquidity case period identities reconcile")
    reset_document()
    base_sweep = float(cell_value(document, "Scenario Comparison", "L5")); set_cell(document, "Assumptions", "D26", 0); document.calculateAll()
    add("ECF sweep assumption changes sweep", float(cell_value(document, "Scenario Comparison", "L5")) < base_sweep, cell_value(document, "Scenario Comparison", "L5"))
    reset_document()
    set_cell(document, "Assumptions", "D24", 400); document.calculateAll()
    add("cash-floor safeguard suppresses sweep", float(cell_value(document, "Scenario Comparison", "L5")) <= base_sweep, cell_value(document, "Scenario Comparison", "L5"))
    reset_document()

    def legacy_weighted_signature() -> float:
        return sum(
            (row - 11) * number("Assumptions", f"D{row}")
            for row in range(12, 36)
        )

    legacy_before = legacy_weighted_signature()
    debt_before_collision = number("Transaction", "D17")
    set_cell(document, "Assumptions", "D12", base_term + 5)
    set_cell(document, "Assumptions", "D13", base_contribution - 7.5)
    document.calculateAll()
    legacy_after = legacy_weighted_signature()
    collision_observed = (
        legacy_before, legacy_after, number("Assumptions", "D15"),
        number("Transaction", "D12"), number("Transaction", "D17"),
        cell_value(document, "Scenario Comparison", "AE12"),
    )
    add("legacy weighted input signature collision is reproduced", abs(legacy_after - legacy_before) <= 0.000001, collision_observed)
    add(
        "typed input state catches balanced funding collision",
        abs(number("Transaction", "D12")) <= 0.000001
        and abs(number("Transaction", "D17") - debt_before_collision - 7.5) <= 0.000001
        and cell_value(document, "Scenario Comparison", "AE12") == "STALE",
        collision_observed,
    )
    reset_document()

    set_cell(document, "Assumptions", "D12", base_term + 1); document.calculateAll()
    add("snapshot stale flag activates", cell_value(document, "Scenario Comparison", "AE12") == "STALE", cell_value(document, "Scenario Comparison", "AE12"))
    reset_document()

    # Scenario-selector probes run only after the live-control probes.  This is a
    # deliberate hard reset boundary for LibreOffice: changing the selected
    # scenario invalidates a large set of cached array dependencies, so later
    # independent probes must not inherit that state.
    set_cell(document, "Assumptions", "D4", "Moderate unmitigated"); document.calculateAll()
    moderate = cell_value(document, "Scenario Comparison", "F5")
    add("scenario selector updates EBITDA", moderate != baseline[0], moderate)
    set_cell(document, "Assumptions", "D4", "Severe unmitigated"); document.calculateAll()
    severe = cell_value(document, "Scenario Comparison", "F5")
    add("severe EBITDA below moderate", isinstance(severe, float) and severe < moderate, severe)
    add("same debt schedule updates", cell_value(document, "Debt Schedule", "D4") == "Severe unmitigated", cell_value(document, "Debt Schedule", "D4"))
    add("historicals remain fixed", historical == document.Sheets.getByName("Historicals").getCellRangeByName("C7:N50").getDataArray(), "unchanged")
    add_identity_test("Selected severe case period identities reconcile")
    add_q2_cfads_test("Selected severe case Forecast and financing Q2 CFADS reconcile")

    reset_document()
    set_cell(document, "Assumptions", "D4", "Moderate Phase 7 covenant-linked no-waiver"); document.calculateAll()
    add("covenant-linked draw shutoff is visible", str(cell_value(document, "Scenario Comparison", "U5")) not in {"", "N/D"}, cell_value(document, "Scenario Comparison", "U5"))
    shutoff_rows = [
        row for row in range(12, 48)
        if cell_value(document, "Debt Schedule", f"AD{row}") == "SHUTOFF"
    ]
    first_shutoff = min(shutoff_rows) if shutoff_rows else None
    same_period_draw = number("Debt Schedule", f"P{first_shutoff}") if first_shutoff else 0.0
    post_shutoff_draws = sum(
        number("Debt Schedule", f"P{row}") for row in shutoff_rows
        if first_shutoff is not None and row > first_shutoff
    )
    add(
        "no-waiver shutoff prevents new revolver draws",
        bool(shutoff_rows) and abs(post_shutoff_draws) <= 0.000001,
        (first_shutoff, same_period_draw, post_shutoff_draws),
    )
    add_identity_test("No-waiver stress period identities reconcile")

    reset_document()
    restored = tuple(cell_value(document, "Scenario Comparison", address) for address in ("F5", "I5", "J5", "L5", "P5", "Q5", "X5"))
    add("Base parity restored", all(abs(float(a) - float(b)) < 0.002 for a, b in zip(restored, baseline)), restored)
    add("final scenario restored to Base", cell_value(document, "Assumptions", "D4") == "Base", cell_value(document, "Assumptions", "D4"))
    failed = [row for row in results if row["status"] != "PASS"]
    return {"dynamic_status": "PASS" if not failed else "FAIL", "test_count": len(results), "tests": results}, document


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"capture", "inspect", "dynamic"}:
        raise SystemExit("usage: recalculate-phase8.py capture|inspect|dynamic workbook.xlsx report.json")
    mode, workbook, report = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    profile = Path(tempfile.mkdtemp(prefix="quanex-lo-profile-"))
    process = None
    document = None
    try:
        process, desktop = connect_office(profile)
        document = open_workbook(desktop, workbook)
        document.calculateAll()
        output: dict[str, object] = {"engine": ENGINE}
        if mode == "capture":
            output["captures"] = capture(document)
        elif mode == "dynamic":
            dynamic_output, document = dynamic_tests(document, desktop, workbook)
            output.update(dynamic_output)
        else:
            configure_print(document)
            document.calculateAll()
            document.store()
        output["final_scenario"] = cell_value(document, "Assumptions", "D4")
        output["parity"] = parity(document)
        output["checks"] = workbook_checks(document)
        report.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"mode": mode, "engine": ENGINE, "status": output.get("dynamic_status", "PASS")}))
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                # A dynamic probe may have already closed the original document
                # while reopening the untouched disposable workbook.
                pass
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
