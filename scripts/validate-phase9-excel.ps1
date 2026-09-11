param([string]$WorkbookPath = "")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $WorkbookPath) { $WorkbookPath = Join-Path $root "model\Quanex_Credit_Underwriting.xlsx" }
$source = (Resolve-Path -LiteralPath $WorkbookPath).Path
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("quanex-phase9-excel-" + [Guid]::NewGuid().ToString("N"))
$started = [DateTime]::UtcNow
$beforePids = @(Get-Process EXCEL -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$excel = $null

function Get-FormulaCount($book) {
    $count = 0
    foreach ($sheet in @($book.Worksheets)) {
        $formulas = $null
        try {
            $formulas = $sheet.UsedRange.SpecialCells(-4123)
            $count += $formulas.Count
        } catch { if ($_.Exception.HResult -ne -2146827284) { throw } }
        finally { if ($formulas) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($formulas) } }
    }
    return $count
}

function Get-WorkbookErrors($book) {
    $items = @()
    foreach ($sheet in @($book.Worksheets)) {
        foreach ($cellType in @(-4123, 2)) {
            $errors = $null
            try { $errors = $sheet.UsedRange.SpecialCells($cellType, 16) } catch {}
            if ($errors) {
                foreach ($cell in @($errors.Cells)) {
                    $items += "$($sheet.Name)!$($cell.Address($false,$false))=$([string]$cell.Text)"
                    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($cell)
                }
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($errors)
            }
        }
        $formulas = $null
        try { $formulas = $sheet.UsedRange.SpecialCells(-4123) } catch {}
        if ($formulas) {
            foreach ($cell in @($formulas.Cells)) {
                if ([string]$cell.Formula -match "#REF!") {
                    $items += "$($sheet.Name)!$($cell.Address($false,$false)) formula contains #REF!"
                }
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($cell)
            }
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($formulas)
        }
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
        "calculate_sheet" { [void]$book.Worksheets.Item("Recovery").Calculate() }
        "f9" { [void]$application.Calculate() }
        "ctrl_alt_f9" { [void]$application.CalculateFull() }
        "ctrl_alt_shift_f9" { [void]$application.CalculateFullRebuild() }
        default { throw "Unsupported calculation method: $method" }
    }
    Wait-ForCalculation $application
}

function Get-InputSnapshot($assumptions, [string]$address) {
    $cell = $assumptions.Range($address)
    $validationType = "none"
    try { $validationType = [string]$cell.Validation.Type } catch {}
    return [pscustomobject]@{
        cell = $address
        value = $cell.Value2
        text = [string]$cell.Text
        number_format = [string]$cell.NumberFormat
        style = [string]$cell.Style.Name
        formula = [string]$cell.Formula
        has_formula = [bool]$cell.HasFormula
        validation_type = $validationType
    }
}

function Assert-MultipleInputs($assumptions) {
    foreach ($address in @("I32", "J32", "K32")) {
        $cell = $assumptions.Range($address)
        if ($cell.Value2 -isnot [ValueType]) { throw "$address is not numeric" }
        if ([string]$cell.NumberFormat -notmatch "x" -or [string]$cell.NumberFormat -match "%") {
            throw "$address does not use a multiple format: $($cell.NumberFormat)"
        }
    }
    if ([string]$assumptions.Range("J32").Text -ne "4.00x") {
        throw "J32 initial visible text was not 4.00x: $($assumptions.Range('J32').Text)"
    }
}

function Assert-BaseChain($recovery) {
    $cells = @()
    foreach ($row in 22..30) { $cells += "E$row" }
    foreach ($row in 39..42) { $cells += "F$row"; $cells += "G$row" }
    foreach ($address in $cells) {
        $cell = $recovery.Range($address)
        try { [void][double]$cell.Value2 } catch { throw "Expected numeric Base-chain cell $address; found $($cell.Text)" }
        if ([string]$cell.Formula -match "#REF!" -or [string]$cell.Text -eq "#REF!") {
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
    try {
        $book = $application.Workbooks.Open($candidate)
        $checks = $book.Worksheets.Item("Checks")
        $assumptions = $book.Worksheets.Item("Assumptions")
        $summary = $book.Worksheets.Item("Credit Summary")
        $recovery = $book.Worksheets.Item("Recovery")
        Assert-MultipleInputs $assumptions
        $initialInputs = @("I32", "J32", "K32") | ForEach-Object { Get-InputSnapshot $assumptions $_ }
        $initialErrors = @(Get-WorkbookErrors $book)
        if ($initialErrors.Count -ne 0) { throw "Initial Excel errors: $($initialErrors -join ', ')" }
        $initialFormulaCount = Get-FormulaCount $book
        $initialChecksFormulaCount = $checks.UsedRange.SpecialCells(-4123).Count
        $baseRecovery = [double]$recovery.Range("E28").Value2
        $baseFormula = [string]$recovery.Range("E28").Formula
        $chain = Assert-BaseChain $recovery

        $assumptions.Range("J32").Value2 = 4.5
        Invoke-Calculation $application $book $method
        if ([Math]::Abs(([double]$assumptions.Range("J32").Value2) - 4.5) -gt 0.000001) { throw "J32 did not retain numeric 4.5" }
        if ([string]$assumptions.Range("J32").Text -ne "4.50x") { throw "J32 did not display 4.50x: $($assumptions.Range('J32').Text)" }
        if ([string]$assumptions.Range("J32").NumberFormat -match "%") { throw "J32 changed to a percentage format" }
        $changedRecovery = [double]$recovery.Range("E28").Value2
        if ([Math]::Abs($changedRecovery - 465.32232829751649) -gt 0.002) { throw "E28 did not recalculate to expected proceeds: $changedRecovery" }
        if ([string]$recovery.Range("E28").Formula -ne $baseFormula) { throw "E28 formula changed after the input edit" }
        [void](Assert-BaseChain $recovery)
        $changedErrors = @(Get-WorkbookErrors $book)
        if ($changedErrors.Count -ne 0) { throw "Excel errors after J32 edit: $($changedErrors -join ', ')" }
        if ([string]$recovery.Range("D45").Value2 -ne "N/D") { throw "Official facility recovery did not remain N/D" }

        $assumptions.Range("J32").Value2 = 4.0
        Invoke-Calculation $application $book $method
        $restoredRecovery = [double]$recovery.Range("E28").Value2
        if ([Math]::Abs($restoredRecovery - $baseRecovery) -gt 0.002) { throw "Restoring J32 did not restore Base proceeds" }
        if ([string]$assumptions.Range("J32").Text -ne "4.00x") { throw "J32 did not restore the 4.00x display" }
        if ([string]$assumptions.Range("D4").Value2 -ne "Base") { throw "Workbook scenario changed from Base" }
        $phase9Failures = $application.WorksheetFunction.CountIf($checks.Range("G42:G58"), "FAIL")
        if ($phase9Failures -ne 0) { throw "Phase 9 terminal checks contain failures" }

        $reopenResult = $null
        if ($saveAndReopen) {
            $book.SaveAs($saved, 51)
            $book.Close($false)
            foreach ($item in @($recovery, $summary, $assumptions, $checks, $book)) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($item) }
            $book = $null
            $reopened = $application.Workbooks.Open($saved)
            $a2 = $reopened.Worksheets.Item("Assumptions"); $r2 = $reopened.Worksheets.Item("Recovery")
            $reopenedFormulaCount = Get-FormulaCount $reopened
            $reopenedErrors = @(Get-WorkbookErrors $reopened)
            if ($reopenedFormulaCount -ne $initialFormulaCount) { throw "Formula count changed after Excel save/reopen" }
            if ([string]$a2.Range("J32").Text -ne "4.00x" -or [string]$a2.Range("D4").Value2 -ne "Base") { throw "Save/reopen did not preserve the multiple format or Base" }
            if ([Math]::Abs(([double]$r2.Range("E28").Value2) - $baseRecovery) -gt 0.002) { throw "Save/reopen changed Base recovery" }
            if ($reopenedErrors.Count -ne 0) { throw "Errors after Excel save/reopen: $($reopenedErrors -join ', ')" }
            $reopenResult = [pscustomobject]@{ formula_count = $reopenedFormulaCount; errors = $reopenedErrors.Count; j32_text = [string]$a2.Range("J32").Text; e28 = [double]$r2.Range("E28").Value2 }
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
        if ($reopened) { try { $reopened.Close($false) } catch {}; [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($reopened) }
        if ($book) { try { $book.Close($false) } catch {}; [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($book) }
    }
}

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.AutomationSecurity = 3

    $results = @()
    $results += Invoke-InteractionCase $excel "none" $false
    $results += Invoke-InteractionCase $excel "ribbon_calculate_now" $false
    $results += Invoke-InteractionCase $excel "calculate_sheet" $false
    $results += Invoke-InteractionCase $excel "f9" $false
    $results += Invoke-InteractionCase $excel "ctrl_alt_f9" $false
    $results += Invoke-InteractionCase $excel "ctrl_alt_shift_f9" $true

    $recoveryLogs = @(Get-ChildItem -Path ([IO.Path]::GetTempPath()) -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTimeUtc -ge $started -and $_.Name -match "^(error.*\.xml|.*recovery.*\.xml)$" })
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
    if ($excel) { try { $excel.Quit() } catch {}; [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers(); Start-Sleep -Milliseconds 500
    foreach ($process in @(Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { $beforePids -notcontains $_.Id })) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
