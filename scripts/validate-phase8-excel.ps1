param(
    [string]$WorkbookPath = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $WorkbookPath) {
    $WorkbookPath = Join-Path $root "model\Quanex_Credit_Underwriting.xlsx"
}
$source = (Resolve-Path -LiteralPath $WorkbookPath).Path
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("quanex-phase8-excel-" + [Guid]::NewGuid().ToString("N"))
$candidate = Join-Path $tempRoot "candidate.xlsx"
$saved = Join-Path $tempRoot "excel-calculated.xlsx"
$started = [DateTime]::UtcNow
$excel = $null
$workbook = $null
$reopened = $null
$excelPid = $null
$excelProcessStartUtc = $null
$checks = $null
$assumptions = $null
$summary = $null
$debt = $null
$forecast = $null
$scenarioComparison = $null
$covenants = $null
$liquidity = $null
$transaction = $null
$checks2 = $null
$assumptions2 = $null
$summary2 = $null
$scenarioComparison2 = $null

if (-not ("Quanex.ExcelWindowProcess" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace Quanex {
    public static class ExcelWindowProcess {
        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    }
}
"@
}

function Release-ComObject($value) {
    if ($null -ne $value -and [Runtime.InteropServices.Marshal]::IsComObject($value)) {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($value)
    }
}

function Get-ExcelProcessId($application) {
    [uint32]$processId = 0
    [void][Quanex.ExcelWindowProcess]::GetWindowThreadProcessId(
        [IntPtr]$application.Hwnd, [ref]$processId
    )
    if ($processId -eq 0) { throw "Could not identify the disposable Excel process" }
    return [int]$processId
}

function Open-Workbook($application, [string]$path) {
    $books = $null
    try {
        $books = $application.Workbooks
        return $books.Open($path)
    } finally {
        Release-ComObject $books
    }
}

function Get-Worksheet($book, [string]$name) {
    $worksheets = $null
    try {
        $worksheets = $book.Worksheets
        return $worksheets.Item($name)
    } finally {
        Release-ComObject $worksheets
    }
}

function Get-SheetFormulaCount($sheet) {
    $used = $null
    $formulas = $null
    try {
        $used = $sheet.UsedRange
        try {
            $formulas = $used.SpecialCells(-4123)
            return [int]$formulas.Count
        } catch {
            if ($_.Exception.HResult -ne -2146827284) { throw }
            return 0
        }
    } finally {
        Release-ComObject $formulas
        Release-ComObject $used
    }
}

function Get-FormulaCount($book) {
    $count = 0
    $worksheets = $null
    try {
        $worksheets = $book.Worksheets
        for ($index = 1; $index -le $worksheets.Count; $index++) {
            $sheet = $null
            try {
                $sheet = $worksheets.Item($index)
                $count += Get-SheetFormulaCount $sheet
            } finally {
                Release-ComObject $sheet
            }
        }
    } finally {
        Release-ComObject $worksheets
    }
    return $count
}

function Invoke-FullCalculation($application) {
    $application.CalculateFullRebuild()
    for ($attempt = 0; $attempt -lt 600 -and $application.CalculationState -ne 0; $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    if ($application.CalculationState -ne 0) {
        throw "Excel full calculation did not complete"
    }
}

function Get-Number($sheet, [string]$address) {
    $range = $null
    try {
        $range = $sheet.Range($address)
        $value = $range.Value2
    } finally {
        Release-ComObject $range
    }
    if ($value -isnot [ValueType]) {
        throw "Expected numeric value at $($sheet.Name)!$address; found '$value'"
    }
    return [double]$value
}

function Get-Text($sheet, [string]$address) {
    $range = $null
    try {
        $range = $sheet.Range($address)
        return [string]$range.Value2
    } finally {
        Release-ComObject $range
    }
}

function Get-FormulaState($sheet, [string]$address) {
    $range = $null
    try {
        $range = $sheet.Range($address)
        return [pscustomobject]@{
            has_formula = [bool]$range.HasFormula
            formula = [string]$range.Formula
        }
    } finally {
        Release-ComObject $range
    }
}

function Set-CellValue($sheet, [string]$address, $value) {
    $range = $null
    try {
        $range = $sheet.Range($address)
        # PowerShell 5.1 caches the first COM setter type at a call site.  This
        # helper writes the text scenario selector before numeric sensitivity
        # inputs, so one polymorphic assignment can later try to cast a Double
        # to String.  Keep distinct call sites and preserve native Excel types.
        if ($value -is [string]) {
            $range.Value2 = [string]$value
        } elseif ($value -is [ValueType]) {
            $range.Value2 = [double]$value
        } else {
            $range.Value2 = $value
        }
    } catch {
        $valueType = if ($null -eq $value) { "null" } else { $value.GetType().FullName }
        throw "Failed to set $($sheet.Name)!$address from ${valueType}: $($_.Exception.Message)"
    } finally {
        Release-ComObject $range
    }
}

function Get-ColumnSum($sheet, [string]$column, [int]$firstRow = 12, [int]$lastRow = 47) {
    $total = 0.0
    foreach ($row in $firstRow..$lastRow) { $total += Get-Number $sheet "$column$row" }
    return $total
}

function Assert-Near([double]$observed, [double]$expected, [double]$tolerance, [string]$label) {
    if ([Math]::Abs($observed - $expected) -gt $tolerance) {
        throw "$label failed: observed=$observed expected=$expected tolerance=$tolerance"
    }
}

function Assert-FinancingIdentities($debt, [string]$label) {
    $maximum = 0.0
    foreach ($row in 12..47) {
        $values = @{}
        foreach ($column in @("J","K","L","M","N","O","P","Q","R","T","U","X","Y","Z","AE","AF","AG","AH","AI","AJ","AK","AL","AP")) {
            $values[$column] = Get-Number $debt "$column$row"
        }
        $revolverBeforeMaturity = $values.O + $values.P - $values.Q
        $expectedTerm = [Math]::Max(0.0, $values.J - $values.K - $values.L - [Math]::Max(0.0, $values.M - $revolverBeforeMaturity))
        $expectedRevolver = [Math]::Max(0.0, $revolverBeforeMaturity - $values.M)
        $differences = @(
            [Math]::Abs($values.AP),
            [Math]::Abs($values.N - $expectedTerm),
            [Math]::Abs($values.R - $expectedRevolver),
            [Math]::Abs($values.X - $values.N - $values.R),
            [Math]::Abs($values.Z - $values.X - $values.Y),
            [Math]::Abs($values.AF - [Math]::Max(0.0, $values.AE - $values.T)),
            [Math]::Abs($values.AH - [Math]::Max(0.0, $values.AG - $values.K)),
            [Math]::Abs($values.AJ - [Math]::Max(0.0, $values.AI - $values.U)),
            [Math]::Abs($values.AL - [Math]::Max(0.0, $values.AK - $values.M))
        )
        $rowMaximum = ($differences | Measure-Object -Maximum).Maximum
        if ($rowMaximum -gt $maximum) { $maximum = $rowMaximum }
    }
    if ($maximum -gt 0.000001) { throw "$label financing identity difference was $maximum" }
    return $maximum
}

function Assert-Q2-Cfads($forecast, $debt, [string]$label) {
    $forecastValue = Get-Number $forecast "D22"
    $financingValue = Get-ColumnSum $debt "I" 12 14
    Assert-Near $financingValue $forecastValue 0.000001 "$label Q2 CFADS"
    return $financingValue
}

function Assert-CapturesCurrent($scenarioComparison, $checks, [string]$label) {
    $currentRows = @()
    $staleRows = @()
    foreach ($row in 12..20) {
        $status = Get-Text $scenarioComparison "AE$row"
        if ($status -eq "CURRENT") {
            $currentRows += $row
        } else {
            $staleRows += "$row`:$status"
        }
    }
    $freshnessCount = Get-Number $checks "D22"
    $staleCount = Get-Number $checks "D33"
    $freshnessStatus = Get-Text $checks "G22"
    $staleStatus = Get-Text $checks "G33"
    if (
        $currentRows.Count -ne 9 -or $staleRows.Count -ne 0 -or
        [Math]::Abs($freshnessCount) -gt 0.000001 -or
        [Math]::Abs($staleCount) -gt 0.000001 -or
        $freshnessStatus -ne "PASS" -or $staleStatus -ne "PASS"
    ) {
        throw "$label capture freshness failed: current=$($currentRows.Count); stale=$($staleRows -join ','); Checks!D22=$freshnessCount; Checks!G22=$freshnessStatus; Checks!D33=$staleCount; Checks!G33=$staleStatus"
    }
    return [pscustomobject]@{
        checkpoint = $label
        status = "PASS"
        current_capture_count = $currentRows.Count
        stale_capture_count = $staleRows.Count
        checks_freshness_status = $freshnessStatus
        checks_stale_status = $staleStatus
    }
}

function Reset-ApprovedBase($application, $assumptions) {
    Set-CellValue $assumptions "D4" "Base"
    Set-CellValue $assumptions "D12" 635.0
    Set-CellValue $assumptions "D13" 15.0
    Set-CellValue $assumptions "D18" 0.075
    Set-CellValue $assumptions "D19" 0.0657
    Set-CellValue $assumptions "D20" 0.0
    Set-CellValue $assumptions "D21" 0.0
    Set-CellValue $assumptions "D23" 0.0
    Set-CellValue $assumptions "D24" 25.0
    Set-CellValue $assumptions "D25" 0.0
    Set-CellValue $assumptions "D26" 0.5
    Set-CellValue $assumptions "D33" 3.5
    Set-CellValue $assumptions "D34" 75.0
    Invoke-FullCalculation $application
}

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    Copy-Item -LiteralPath $source -Destination $candidate
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.AutomationSecurity = 3
    $excelPid = Get-ExcelProcessId $excel
    $excelProcessStartUtc = (Get-Process -Id $excelPid -ErrorAction Stop).StartTime.ToUniversalTime()

    $workbook = Open-Workbook $excel $candidate
    $initialFormulaCount = Get-FormulaCount $workbook
    $checks = Get-Worksheet $workbook "Checks"
    $assumptions = Get-Worksheet $workbook "Assumptions"
    $summary = Get-Worksheet $workbook "Credit Summary"
    $debt = Get-Worksheet $workbook "Debt Schedule"
    $forecast = Get-Worksheet $workbook "Forecast"
    $scenarioComparison = Get-Worksheet $workbook "Scenario Comparison"
    $covenants = Get-Worksheet $workbook "Covenants"
    $liquidity = Get-Worksheet $workbook "Liquidity"
    $transaction = Get-Worksheet $workbook "Transaction"
    $probeResults = @()
    $initialChecksFormulaCount = Get-SheetFormulaCount $checks
    $selectorState = Get-FormulaState $checks "G20"
    if (-not $selectorState.has_formula -or $selectorState.formula -notlike "=IF(OR(*") {
        throw "Checks!G20 did not retain the Excel-compatible formula"
    }
    $phase9Present = Test-Path -LiteralPath (Join-Path $root "data\phase9")
    if ((-not $phase9Present -and ($initialFormulaCount -ne 2771 -or $initialChecksFormulaCount -ne 66)) -or
        ($phase9Present -and ($initialFormulaCount -lt 2771 -or $initialChecksFormulaCount -lt 66))) {
        throw "Unexpected formula count before Excel calculation"
    }
    if ((Get-Text $assumptions "D4") -ne "Base") {
        throw "Workbook was not initially saved in Base"
    }
    Invoke-FullCalculation $excel
    $initialFreshness = Assert-CapturesCurrent $scenarioComparison $checks "initial_full_calculation"
    $baseEbitda = Get-Number $summary "D17"
    Set-CellValue $assumptions "D4" "Moderate unmitigated"
    Invoke-FullCalculation $excel
    $moderateEbitda = Get-Number $summary "D17"
    if ([Math]::Abs($moderateEbitda - $baseEbitda) -lt 0.001) {
        throw "Non-Base scenario did not update the linked output"
    }
    Set-CellValue $assumptions "D4" "Base"
    Invoke-FullCalculation $excel

    $baselineQ2Cfads = Assert-Q2-Cfads $forecast $debt "Base"
    $baselineInterestDue = Get-ColumnSum $debt "AE"
    $baselineInterestPaid = Get-ColumnSum $debt "T"
    $baselineAprilPrincipal = Get-Number $debt "K14"
    $baselineMaturityGap = Get-Number $scenarioComparison "X5"
    $baselineLiquidity = Get-Number $scenarioComparison "P5"
    $baselineDebt = Get-Number $transaction "D17"
    $baselineCoverageWarning = Get-Number $assumptions "D33"
    $baselineLiquidityWarning = Get-Number $assumptions "D34"
    Assert-Near $baselineCoverageWarning 3.5 0.000001 "Approved coverage warning threshold"
    Assert-Near $baselineLiquidityWarning 75.0 0.000001 "Approved liquidity warning threshold"
    $probeResults += [pscustomobject]@{ case = "base"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "Base"); q2_cfads = $baselineQ2Cfads; q2_cfads_difference = ($baselineQ2Cfads - (Get-Number $forecast "D22")) }

    # Q-009: each advertised input is exercised independently on this
    # disposable Excel copy and reset before the next probe.
    Set-CellValue $assumptions "D20" 0.01
    Invoke-FullCalculation $excel
    $spreadDue = Get-ColumnSum $debt "AE"
    $spreadPaid = Get-ColumnSum $debt "T"
    if ($spreadDue -le $baselineInterestDue -or $spreadPaid -le $baselineInterestPaid) { throw "Spread probe did not increase interest due and paid" }
    $probeResults += [pscustomobject]@{ case = "spread_plus_100bp"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "Spread +100bp"); february_cash_identity = (Get-Number $debt "AP12"); april_cash_identity = (Get-Number $debt "AP14"); interest_due = $spreadDue; interest_paid = $spreadPaid }
    Reset-ApprovedBase $excel $assumptions

    Set-CellValue $assumptions "D18" 0.10
    Invoke-FullCalculation $excel
    $aprilPrincipal = Get-Number $debt "K14"
    if ($aprilPrincipal -le $baselineAprilPrincipal) { throw "Amortization probe did not increase April scheduled principal" }
    $probeResults += [pscustomobject]@{ case = "amortization_10_percent"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "Amortization 10%"); april_cash_identity = (Get-Number $debt "AP14"); april_scheduled_principal = $aprilPrincipal; maturity_gap = (Get-Number $scenarioComparison "X5") }
    Reset-ApprovedBase $excel $assumptions

    Set-CellValue $assumptions "D21" 0.10
    Invoke-FullCalculation $excel
    $ebitdaCfads = Assert-Q2-Cfads $forecast $debt "EBITDA +10%"
    if ($ebitdaCfads -le $baselineQ2Cfads) { throw "EBITDA probe did not increase Q2 CFADS" }
    $probeResults += [pscustomobject]@{ case = "fy2026_q2_ebitda_plus_10_percent"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "EBITDA +10%"); q2_cfads = $ebitdaCfads; q2_cfads_difference = ($ebitdaCfads - (Get-Number $forecast "D22")) }
    Reset-ApprovedBase $excel $assumptions

    Set-CellValue $assumptions "D23" 10.0
    Invoke-FullCalculation $excel
    $dsoCfads = Assert-Q2-Cfads $forecast $debt "DSO +10 days"
    if ($dsoCfads -ge $baselineQ2Cfads) { throw "DSO probe did not reduce Q2 CFADS" }
    $probeResults += [pscustomobject]@{ case = "dso_plus_10_days"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "DSO +10 days"); q2_cfads = $dsoCfads; q2_cfads_difference = ($dsoCfads - (Get-Number $forecast "D22")) }
    Reset-ApprovedBase $excel $assumptions

    Set-CellValue $assumptions "D18" 0.10
    Set-CellValue $assumptions "D20" 0.01
    Set-CellValue $assumptions "D21" -0.10
    Set-CellValue $assumptions "D23" 10.0
    Invoke-FullCalculation $excel
    $combinedCfads = Assert-Q2-Cfads $forecast $debt "Combined adverse controls"
    $combinedGap = Get-Number $scenarioComparison "X5"
    $combinedLiquidity = Get-Number $scenarioComparison "P5"
    if ($combinedGap -le $baselineMaturityGap -and $combinedLiquidity -ge $baselineLiquidity) {
        throw "Combined adverse controls did not worsen maturity gap or liquidity"
    }
    $probeResults += [pscustomobject]@{ case = "combined_rate_amortization_ebitda_dso"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "Combined controls"); q2_cfads = $combinedCfads; q2_cfads_difference = ($combinedCfads - (Get-Number $forecast "D22")); maturity_gap = $combinedGap; liquidity = $combinedLiquidity }
    Reset-ApprovedBase $excel $assumptions

    Set-CellValue $assumptions "D25" -500.0
    Invoke-FullCalculation $excel
    $shortfalls = (Get-ColumnSum $debt "AF") + (Get-ColumnSum $debt "AH") + (Get-ColumnSum $debt "AJ")
    if ($shortfalls -le 0.001) { throw "Tight-liquidity case did not expose mandatory-payment shortfalls" }
    $probeResults += [pscustomobject]@{ case = "tight_liquidity"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "Tight liquidity"); mandatory_shortfalls = $shortfalls; minimum_liquidity = (Get-Number $scenarioComparison "P5") }
    Reset-ApprovedBase $excel $assumptions

    Set-CellValue $assumptions "D4" "Moderate Phase 7 covenant-linked no-waiver"
    Invoke-FullCalculation $excel
    $shutoffRows = @()
    $drawsAfterShutoff = 0.0
    foreach ($row in 12..47) {
        if ((Get-Text $debt "AD$row") -eq "SHUTOFF") {
            $shutoffRows += $row
            $drawsAfterShutoff += Get-Number $debt "P$row"
        }
    }
    if ($shutoffRows.Count -eq 0 -or [Math]::Abs($drawsAfterShutoff) -gt 0.000001) { throw "No-waiver draw shutoff was not preserved" }
    $probeResults += [pscustomobject]@{ case = "no_waiver_stress"; status = "PASS"; max_identity_difference = (Assert-FinancingIdentities $debt "No-waiver stress"); shutoff_periods = $shutoffRows.Count; draws_after_shutoff = $drawsAfterShutoff }
    Reset-ApprovedBase $excel $assumptions

    # Q-007 collision counterexample: term +5, contribution -7.5 and the
    # balancing revolver +2.5 leave the legacy weighted sum unchanged while
    # total debt increases by 7.5.  The typed live state must flag every capture.
    $typedStateBefore = Get-Text $assumptions "D7"
    Set-CellValue $assumptions "D12" 640.0
    Set-CellValue $assumptions "D13" 7.5
    Invoke-FullCalculation $excel
    Assert-Near (Get-Number $transaction "D12") 0.0 0.000001 "Balanced funding collision"
    Assert-Near (Get-Number $transaction "D17") ($baselineDebt + 7.5) 0.000001 "Collision debt change"
    if ((Get-Text $assumptions "D7") -eq $typedStateBefore -or (Get-Text $scenarioComparison "AE12") -ne "STALE") {
        throw "Typed freshness state did not detect the balanced funding collision"
    }
    $probeResults += [pscustomobject]@{ case = "balanced_funding_signature_collision"; status = "PASS"; stale_status = (Get-Text $scenarioComparison "AE12"); debt_change = 7.5 }
    Reset-ApprovedBase $excel $assumptions

    # Q-005 warning equality is inclusive in the executed workbook.
    $coverageMeasure = Get-Number $covenants "N12"
    Set-CellValue $assumptions "D33" $coverageMeasure
    Invoke-FullCalculation $excel
    if ((Get-Text $covenants "R12") -ne "WARNING") { throw "Coverage equality did not trigger WARNING" }
    Reset-ApprovedBase $excel $assumptions
    $liquidityMeasure = Get-Number $liquidity "P13"
    Set-CellValue $assumptions "D34" $liquidityMeasure
    Invoke-FullCalculation $excel
    if ((Get-Text $liquidity "R13") -ne "WARNING") { throw "Liquidity equality did not trigger WARNING" }
    $probeResults += [pscustomobject]@{ case = "warning_threshold_equalities"; status = "PASS"; coverage_threshold = $baselineCoverageWarning; liquidity_threshold = $baselineLiquidityWarning; coverage_status = "WARNING"; liquidity_status = "WARNING" }
    Reset-ApprovedBase $excel $assumptions

    $preSaveFreshness = Assert-CapturesCurrent $scenarioComparison $checks "pre_save_base_reset"
    $workbook.SaveAs($saved, 51)
    foreach ($child in @($summary, $assumptions, $checks, $debt, $forecast, $scenarioComparison, $covenants, $liquidity, $transaction)) {
        Release-ComObject $child
    }
    $summary = $null
    $assumptions = $null
    $checks = $null
    $debt = $null
    $forecast = $null
    $scenarioComparison = $null
    $covenants = $null
    $liquidity = $null
    $transaction = $null
    $workbook.Close($false)
    Release-ComObject $workbook
    $workbook = $null

    $reopened = Open-Workbook $excel $saved
    $reopenedFormulaCount = Get-FormulaCount $reopened
    $checks2 = Get-Worksheet $reopened "Checks"
    $assumptions2 = Get-Worksheet $reopened "Assumptions"
    $summary2 = Get-Worksheet $reopened "Credit Summary"
    $scenarioComparison2 = Get-Worksheet $reopened "Scenario Comparison"
    Invoke-FullCalculation $excel
    $reopenedChecksFormulaCount = Get-SheetFormulaCount $checks2
    if ($reopenedFormulaCount -ne $initialFormulaCount -or $reopenedChecksFormulaCount -ne $initialChecksFormulaCount) {
        throw "Formula count changed after Excel save and reopen"
    }
    $reopenedSelectorState = Get-FormulaState $checks2 "G20"
    if (-not $reopenedSelectorState.has_formula -or (Get-Text $assumptions2 "D4") -ne "Base") {
        throw "Excel save/reopen did not preserve Checks!G20 or Base"
    }
    if ([Math]::Abs((Get-Number $summary2 "D17") - $baseEbitda) -gt 0.002) {
        throw "Base output changed after Excel save and reopen"
    }
    $reopenedFreshness = Assert-CapturesCurrent $scenarioComparison2 $checks2 "save_reopen_full_calculation"
    Release-ComObject $scenarioComparison2
    Release-ComObject $summary2
    Release-ComObject $assumptions2
    Release-ComObject $checks2
    $summary2 = $null
    $assumptions2 = $null
    $checks2 = $null
    $reopened.Close($false)
    Release-ComObject $reopened
    $reopened = $null

    $recoveryLogs = @(Get-ChildItem -Path $tempRoot -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -ge $started -and $_.Name -match "^(error.*\.xml|.*recovery.*\.xml)$" })
    if ($recoveryLogs.Count -ne 0) {
        throw "Excel generated a recovery log: $($recoveryLogs.FullName -join ', ')"
    }

    [pscustomobject]@{
        status = "PASS"
        excel_version = [string]$excel.Version
        excel_build = [string]$excel.Build
        formula_count = $reopenedFormulaCount
        checks_formula_count = $reopenedChecksFormulaCount
        base_ebitda = $baseEbitda
        moderate_unmitigated_ebitda = $moderateEbitda
        live_input_probes = $probeResults
        freshness_checkpoints = @($initialFreshness, $preSaveFreshness, $reopenedFreshness)
        final_scenario = "Base"
        recovery_logs = 0
    } | ConvertTo-Json
} finally {
    foreach ($child in @($scenarioComparison2, $summary2, $assumptions2, $checks2, $summary, $assumptions, $checks, $debt, $forecast, $scenarioComparison, $covenants, $liquidity, $transaction)) {
        Release-ComObject $child
    }
    $scenarioComparison2 = $null
    $summary2 = $null
    $assumptions2 = $null
    $checks2 = $null
    $summary = $null
    $assumptions = $null
    $checks = $null
    $debt = $null
    $forecast = $null
    $scenarioComparison = $null
    $covenants = $null
    $liquidity = $null
    $transaction = $null
    if ($reopened) {
        try { $reopened.Close($false) } catch {}
        Release-ComObject $reopened
        $reopened = $null
    }
    if ($workbook) {
        try { $workbook.Close($false) } catch {}
        Release-ComObject $workbook
        $workbook = $null
    }
    if ($excel) {
        try { $excel.Quit() } catch {}
        Release-ComObject $excel
        $excel = $null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    Start-Sleep -Milliseconds 500
    $remainingExcelProcess = if ($excelPid) { Get-Process -Id $excelPid -ErrorAction SilentlyContinue } else { $null }
    if ($remainingExcelProcess -and $excelProcessStartUtc -and $remainingExcelProcess.StartTime.ToUniversalTime() -eq $excelProcessStartUtc) {
        Stop-Process -Id $excelPid -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
