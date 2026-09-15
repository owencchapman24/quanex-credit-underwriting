param([string]$WorkbookPath = "")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $WorkbookPath) { $WorkbookPath = Join-Path $root "model\Quanex_Credit_Underwriting.xlsx" }
$source = (Resolve-Path -LiteralPath $WorkbookPath).Path
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("quanex-phase9-excel-" + [Guid]::NewGuid().ToString("N"))
$started = [DateTime]::UtcNow
$excel = $null
$excelPid = $null
$excelProcessStartUtc = $null

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

function Get-CellSnapshot($sheet, [string]$address) {
    $cell = $null
    $validation = $null
    $style = $null
    try {
        $cell = $sheet.Range($address)
        $validationType = "none"
        try {
            $validation = $cell.Validation
            $validationType = [string]$validation.Type
        } catch {}
        $styleName = ""
        try {
            $style = $cell.Style
            $styleName = if ([Runtime.InteropServices.Marshal]::IsComObject($style)) { [string]$style.Name } else { [string]$style }
        } catch {}
        return [pscustomobject]@{
            cell = $address
            value = $cell.Value2
            text = [string]$cell.Text
            number_format = [string]$cell.NumberFormat
            style = $styleName
            formula = [string]$cell.Formula
            has_formula = [bool]$cell.HasFormula
            validation_type = $validationType
        }
    } finally {
        Release-ComObject $style
        Release-ComObject $validation
        Release-ComObject $cell
    }
}

function Set-CellValue($sheet, [string]$address, $value) {
    $cell = $null
    try {
        $cell = $sheet.Range($address)
        $cell.Value2 = $value
    } finally {
        Release-ComObject $cell
    }
}

function Get-SheetFormulaCount($sheet) {
    $used = $null
    $formulas = $null
    try {
        $used = $sheet.UsedRange
        if ($null -eq $used) { throw "Excel returned no UsedRange for worksheet $($sheet.Name)" }
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

function Get-WorkbookErrors($book) {
    $items = @()
    $worksheets = $null
    try {
        $worksheets = $book.Worksheets
        for ($sheetIndex = 1; $sheetIndex -le $worksheets.Count; $sheetIndex++) {
            $sheet = $null
            try {
                $sheet = $worksheets.Item($sheetIndex)
                foreach ($cellType in @(-4123, 2)) {
                    $used = $null
                    $errors = $null
                    try {
                        $used = $sheet.UsedRange
                        try { $errors = $used.SpecialCells($cellType, 16) } catch {}
                        if ($errors) {
                            $cells = $null
                            try {
                                $cells = $errors.Cells
                                for ($cellIndex = 1; $cellIndex -le $cells.Count; $cellIndex++) {
                                    $cell = $null
                                    try {
                                        $cell = $cells.Item($cellIndex)
                                        $items += "$($sheet.Name)!$($cell.Address($false,$false))=$([string]$cell.Text)"
                                    } finally {
                                        Release-ComObject $cell
                                    }
                                }
                            } finally {
                                Release-ComObject $cells
                            }
                        }
                    } finally {
                        Release-ComObject $errors
                        Release-ComObject $used
                    }
                }

                $used = $null
                $formulas = $null
                try {
                    $used = $sheet.UsedRange
                    try { $formulas = $used.SpecialCells(-4123) } catch {}
                    if ($formulas) {
                        $cells = $null
                        try {
                            $cells = $formulas.Cells
                            for ($cellIndex = 1; $cellIndex -le $cells.Count; $cellIndex++) {
                                $cell = $null
                                try {
                                    $cell = $cells.Item($cellIndex)
                                    if ([string]$cell.Formula -match "#REF!") {
                                        $items += "$($sheet.Name)!$($cell.Address($false,$false)) formula contains #REF!"
                                    }
                                } finally {
                                    Release-ComObject $cell
                                }
                            }
                        } finally {
                            Release-ComObject $cells
                        }
                    }
                } finally {
                    Release-ComObject $formulas
                    Release-ComObject $used
                }
            } finally {
                Release-ComObject $sheet
            }
        }
    } finally {
        Release-ComObject $worksheets
    }
    return @($items | Sort-Object -Unique)
}

function Wait-ForCalculation($application) {
    for ($attempt = 0; $attempt -lt 600 -and $application.CalculationState -ne 0; $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    if ($application.CalculationState -ne 0) { throw "Excel calculation did not complete" }
}

function Invoke-Calculation($application, $book, [string]$method) {
    switch ($method) {
        "none" { }
        "ribbon_calculate_now" { [void]$application.Calculate() }
        "calculate_sheet" {
            $recovery = $null
            try {
                $recovery = Get-Worksheet $book "Recovery"
                [void]$recovery.Calculate()
            } finally {
                Release-ComObject $recovery
            }
        }
        "f9" { [void]$application.Calculate() }
        "ctrl_alt_f9" { [void]$application.CalculateFull() }
        "ctrl_alt_shift_f9" { [void]$application.CalculateFullRebuild() }
        default { throw "Unsupported calculation method: $method" }
    }
    Wait-ForCalculation $application
}

function Get-InputSnapshot($assumptions, [string]$address) {
    return Get-CellSnapshot $assumptions $address
}

function Assert-MultipleInputs($assumptions) {
    foreach ($address in @("I32", "J32", "K32")) {
        $cell = Get-CellSnapshot $assumptions $address
        if ($cell.value -isnot [ValueType]) { throw "$address is not numeric" }
        if ($cell.number_format -notmatch "x" -or $cell.number_format -match "%") {
            throw "$address does not use a multiple format: $($cell.number_format)"
        }
    }
    $j32 = Get-CellSnapshot $assumptions "J32"
    if ($j32.text -ne "4.00x") {
        throw "J32 initial visible text was not 4.00x: $($j32.text)"
    }
}

function Assert-BaseChain($recovery) {
    $cells = @()
    foreach ($row in 22..30) { $cells += "E$row" }
    foreach ($row in 39..42) { $cells += "F$row"; $cells += "G$row" }
    foreach ($address in $cells) {
        $cell = Get-CellSnapshot $recovery $address
        try { [void][double]$cell.value } catch { throw "Expected numeric Base-chain cell $address; found $($cell.text)" }
        if ($cell.formula -match "#REF!" -or $cell.text -eq "#REF!") {
            throw "Base-chain error at Recovery!$address"
        }
    }
    return $cells
}

function Invoke-InteractionCase($application, [string]$method, [bool]$saveAndReopen) {
    $candidate = Join-Path $tempRoot ("candidate-" + $method + ".xlsx")
    $saved = Join-Path $tempRoot ("saved-" + $method + ".xlsx")
    Copy-Item -LiteralPath $source -Destination $candidate
    $book = $null; $reopened = $null
    $checks = $null; $assumptions = $null; $summary = $null; $recovery = $null
    $a2 = $null; $r2 = $null
    try {
        $book = Open-Workbook $application $candidate
        $checks = Get-Worksheet $book "Checks"
        $assumptions = Get-Worksheet $book "Assumptions"
        $summary = Get-Worksheet $book "Credit Summary"
        $recovery = Get-Worksheet $book "Recovery"
        Assert-MultipleInputs $assumptions
        $initialInputs = @("I32", "J32", "K32") | ForEach-Object { Get-InputSnapshot $assumptions $_ }
        $initialErrors = @(Get-WorkbookErrors $book)
        if ($initialErrors.Count -ne 0) { throw "Initial Excel errors: $($initialErrors -join ', ')" }
        $initialFormulaCount = Get-FormulaCount $book
        $initialChecksFormulaCount = Get-SheetFormulaCount $checks
        $baseRecoveryCell = Get-CellSnapshot $recovery "E28"
        $baseRecovery = [double]$baseRecoveryCell.value
        $baseFormula = $baseRecoveryCell.formula
        $chain = Assert-BaseChain $recovery

        Set-CellValue $assumptions "J32" 4.5
        Invoke-Calculation $application $book $method
        $changedJ32 = Get-CellSnapshot $assumptions "J32"
        if ([Math]::Abs(([double]$changedJ32.value) - 4.5) -gt 0.000001) { throw "J32 did not retain numeric 4.5" }
        if ($changedJ32.text -ne "4.50x") { throw "J32 did not display 4.50x: $($changedJ32.text)" }
        if ($changedJ32.number_format -match "%") { throw "J32 changed to a percentage format" }
        $changedRecoveryCell = Get-CellSnapshot $recovery "E28"
        $changedRecovery = [double]$changedRecoveryCell.value
        if ([Math]::Abs($changedRecovery - 465.32232829751649) -gt 0.002) { throw "E28 did not recalculate to expected proceeds: $changedRecovery" }
        if ($changedRecoveryCell.formula -ne $baseFormula) { throw "E28 formula changed after the input edit" }
        [void](Assert-BaseChain $recovery)
        $changedErrors = @(Get-WorkbookErrors $book)
        if ($changedErrors.Count -ne 0) { throw "Excel errors after J32 edit: $($changedErrors -join ', ')" }
        if ((Get-CellSnapshot $recovery "D45").value -ne "N/D") { throw "Official facility recovery did not remain N/D" }

        Set-CellValue $assumptions "J32" 4.0
        Invoke-Calculation $application $book $method
        $restoredRecovery = [double](Get-CellSnapshot $recovery "E28").value
        if ([Math]::Abs($restoredRecovery - $baseRecovery) -gt 0.002) { throw "Restoring J32 did not restore Base proceeds" }
        if ((Get-CellSnapshot $assumptions "J32").text -ne "4.00x") { throw "J32 did not restore the 4.00x display" }
        if ((Get-CellSnapshot $assumptions "D4").value -ne "Base") { throw "Workbook scenario changed from Base" }
        $worksheetFunction = $null
        $checkRange = $null
        try {
            $worksheetFunction = $application.WorksheetFunction
            $checkRange = $checks.Range("G42:G58")
            $phase9Failures = $worksheetFunction.CountIf($checkRange, "FAIL")
        } finally {
            Release-ComObject $checkRange
            Release-ComObject $worksheetFunction
        }
        if ($phase9Failures -ne 0) { throw "Phase 9 terminal checks contain failures" }

        $reopenResult = $null
        if ($saveAndReopen) {
            $book.SaveAs($saved, 51)
            foreach ($item in @($recovery, $summary, $assumptions, $checks)) { Release-ComObject $item }
            $recovery = $null; $summary = $null; $assumptions = $null; $checks = $null
            $book.Close($false)
            Release-ComObject $book
            $book = $null
            $reopened = Open-Workbook $application $saved
            $a2 = Get-Worksheet $reopened "Assumptions"; $r2 = Get-Worksheet $reopened "Recovery"
            $reopenedFormulaCount = Get-FormulaCount $reopened
            $reopenedErrors = @(Get-WorkbookErrors $reopened)
            if ($reopenedFormulaCount -ne $initialFormulaCount) { throw "Formula count changed after Excel save/reopen" }
            $reopenedJ32 = Get-CellSnapshot $a2 "J32"
            if ($reopenedJ32.text -ne "4.00x" -or (Get-CellSnapshot $a2 "D4").value -ne "Base") { throw "Save/reopen did not preserve the multiple format or Base" }
            $reopenedRecovery = [double](Get-CellSnapshot $r2 "E28").value
            if ([Math]::Abs($reopenedRecovery - $baseRecovery) -gt 0.002) { throw "Save/reopen changed Base recovery" }
            if ($reopenedErrors.Count -ne 0) { throw "Errors after Excel save/reopen: $($reopenedErrors -join ', ')" }
            $reopenResult = [pscustomobject]@{ formula_count = $reopenedFormulaCount; errors = $reopenedErrors.Count; j32_text = $reopenedJ32.text; e28 = $reopenedRecovery }
        }
        return [pscustomobject]@{
            method = $method
            status = "PASS"
            initial_inputs = $initialInputs
            initial_error_count = $initialErrors.Count
            changed_j32_text = "4.50x"
            changed_e28 = $changedRecovery
            changed_error_count = $changedErrors.Count
            restored_j32_text = "4.00x"
            restored_e28 = $restoredRecovery
            base_chain_cells = $chain
            formula_count = $initialFormulaCount
            checks_formula_count = $initialChecksFormulaCount
            reopen = $reopenResult
        }
    } finally {
        foreach ($item in @($r2, $a2, $recovery, $summary, $assumptions, $checks)) { Release-ComObject $item }
        $r2 = $null; $a2 = $null; $recovery = $null; $summary = $null; $assumptions = $null; $checks = $null
        if ($reopened) { try { $reopened.Close($false) } catch {}; Release-ComObject $reopened; $reopened = $null }
        if ($book) { try { $book.Close($false) } catch {}; Release-ComObject $book; $book = $null }
    }
}

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.AutomationSecurity = 3
    $excelPid = Get-ExcelProcessId $excel
    $excelProcessStartUtc = (Get-Process -Id $excelPid -ErrorAction Stop).StartTime.ToUniversalTime()

    $results = @()
    $results += Invoke-InteractionCase $excel "none" $false
    $results += Invoke-InteractionCase $excel "ribbon_calculate_now" $false
    $results += Invoke-InteractionCase $excel "calculate_sheet" $false
    $results += Invoke-InteractionCase $excel "f9" $false
    $results += Invoke-InteractionCase $excel "ctrl_alt_f9" $false
    $results += Invoke-InteractionCase $excel "ctrl_alt_shift_f9" $true

    $recoveryLogs = @(Get-ChildItem -Path $tempRoot -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTimeUtc -ge $started -and $_.Name -match "^(error.*\.xml|.*recovery.*\.xml)$" })
    if ($recoveryLogs.Count -ne 0) { throw "Excel generated a recovery log: $($recoveryLogs.FullName -join ', ')" }
    [pscustomobject]@{
        status = "PASS"
        excel_version = [string]$excel.Version
        excel_build = [string]$excel.Build
        calculation_methods = $results
        formula_count = $results[0].formula_count
        checks_formula_count = $results[0].checks_formula_count
        base_going_concern_allocation = $results[0].restored_e28
        edited_going_concern_allocation = $results[0].changed_e28
        official_recovery = "N/D"
        final_scenario = "Base"
        workbook_error_cells = 0
        recovery_logs = 0
    } | ConvertTo-Json -Depth 9
} finally {
    if ($excel) { try { $excel.Quit() } catch {}; Release-ComObject $excel; $excel = $null }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers(); Start-Sleep -Milliseconds 500
    $remainingExcelProcess = if ($excelPid) { Get-Process -Id $excelPid -ErrorAction SilentlyContinue } else { $null }
    if ($remainingExcelProcess -and $excelProcessStartUtc -and $remainingExcelProcess.StartTime.ToUniversalTime() -eq $excelProcessStartUtc) {
        Stop-Process -Id $excelPid -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
