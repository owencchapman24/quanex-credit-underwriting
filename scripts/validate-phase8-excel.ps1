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
$beforePids = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$excel = $null
$workbook = $null
$reopened = $null
$excelPid = $null

function Get-FormulaCount($book) {
    $count = 0
    foreach ($sheet in @($book.Worksheets)) {
        try {
            $formulas = $sheet.UsedRange.SpecialCells(-4123)
            $count += $formulas.Count
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($formulas)
        } catch {
            if ($_.Exception.HResult -ne -2146827284) { throw }
        } finally {
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sheet)
        }
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

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    Copy-Item -LiteralPath $source -Destination $candidate
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.AutomationSecurity = 3
    $excelPid = @(Get-Process EXCEL -ErrorAction SilentlyContinue |
        Where-Object { $beforePids -notcontains $_.Id } |
        Sort-Object StartTime -Descending |
        Select-Object -First 1 -ExpandProperty Id)

    $workbook = $excel.Workbooks.Open($candidate)
    $initialFormulaCount = Get-FormulaCount $workbook
    $checks = $workbook.Worksheets.Item("Checks")
    $assumptions = $workbook.Worksheets.Item("Assumptions")
    $summary = $workbook.Worksheets.Item("Credit Summary")
    $initialChecksFormulaCount = $checks.UsedRange.SpecialCells(-4123).Count
    $selectorFormula = [string]$checks.Range("G20").Formula
    if (-not $checks.Range("G20").HasFormula -or $selectorFormula -notlike "=IF(OR(*") {
        throw "Checks!G20 did not retain the Excel-compatible formula"
    }
    $phase9Present = Test-Path -LiteralPath (Join-Path $root "data\phase9")
    if ((-not $phase9Present -and ($initialFormulaCount -ne 2771 -or $initialChecksFormulaCount -ne 66)) -or
        ($phase9Present -and ($initialFormulaCount -lt 2771 -or $initialChecksFormulaCount -lt 66))) {
        throw "Unexpected formula count before Excel calculation"
    }
    if ([string]$assumptions.Range("D4").Value2 -ne "Base") {
        throw "Workbook was not initially saved in Base"
    }
    Invoke-FullCalculation $excel
    $baseEbitda = [double]$summary.Range("D17").Value2
    $assumptions.Range("D4").Value2 = "Moderate unmitigated"
    Invoke-FullCalculation $excel
    $moderateEbitda = [double]$summary.Range("D17").Value2
    if ([Math]::Abs($moderateEbitda - $baseEbitda) -lt 0.001) {
        throw "Non-Base scenario did not update the linked output"
    }
    $assumptions.Range("D4").Value2 = "Base"
    Invoke-FullCalculation $excel
    $workbook.SaveAs($saved, 51)
    $workbook.Close($false)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($summary)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($assumptions)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($checks)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
    $workbook = $null

    $reopened = $excel.Workbooks.Open($saved)
    $reopenedFormulaCount = Get-FormulaCount $reopened
    $checks2 = $reopened.Worksheets.Item("Checks")
    $assumptions2 = $reopened.Worksheets.Item("Assumptions")
    $summary2 = $reopened.Worksheets.Item("Credit Summary")
    $reopenedChecksFormulaCount = $checks2.UsedRange.SpecialCells(-4123).Count
    if ($reopenedFormulaCount -ne $initialFormulaCount -or $reopenedChecksFormulaCount -ne $initialChecksFormulaCount) {
        throw "Formula count changed after Excel save and reopen"
    }
    if (-not $checks2.Range("G20").HasFormula -or [string]$assumptions2.Range("D4").Value2 -ne "Base") {
        throw "Excel save/reopen did not preserve Checks!G20 or Base"
    }
    if ([Math]::Abs(([double]$summary2.Range("D17").Value2) - $baseEbitda) -gt 0.002) {
        throw "Base output changed after Excel save and reopen"
    }
    $reopened.Close($false)

    $recoveryLogs = @(Get-ChildItem -Path ([IO.Path]::GetTempPath()) -Recurse -Force -File -ErrorAction SilentlyContinue |
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
        final_scenario = "Base"
        recovery_logs = 0
    } | ConvertTo-Json
} finally {
    if ($reopened) {
        try { $reopened.Close($false) } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($reopened)
    }
    if ($workbook) {
        try { $workbook.Close($false) } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
    }
    if ($excel) {
        try { $excel.Quit() } catch {}
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    Start-Sleep -Milliseconds 500
    if ($excelPid -and (Get-Process -Id $excelPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $excelPid -Force
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
