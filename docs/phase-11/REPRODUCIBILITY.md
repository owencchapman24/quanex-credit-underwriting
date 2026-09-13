# Reproducibility

These instructions document the environment in which full regeneration was tested; they do not claim universal, platform-independent reproducibility. The complete release gate depends on the documented Windows, Python, Node.js, `@oai/artifact-tool`, Microsoft Excel, LibreOffice, and PowerShell environment.

## Tested prerequisites

- Windows with PowerShell 5.1.19041.6456.
- Python 3.14.7 available as `python`; the analytical workflows require only the standard library.
- Bundled Node.js 24.19.0 and `@oai/artifact-tool` 2.8.58+ for workbook generation. The current scripts locate this toolchain in the Codex primary-runtime cache; a non-Codex environment must supply an equivalent runtime and adjust that documented lookup.
- LibreOffice 26.8.0.3 for reproducible full calculation and saved-scenario capture.
- Microsoft Excel for Microsoft 365, version 16.0 build 20326, for the Windows-only compatibility gates.
- Bundled Python 3.12.14 with ReportLab 4.4.9, Pillow 12.3.0, pypdf 6.10.0, and pypdfium2 5.13.0 / PDFium 153.0.7999.0 for PDF/chart generation, inspection, and disposable all-page rendering.
- Git with local-clone support. No Git LFS artifact is required.

Only the Python standard library is required by the analytical Python scripts. No `requirements.txt`, `pyproject.toml`, `package.json`, or lockfile is added because the implemented workflow consumes the bundled document/workbook runtimes rather than installing project packages.

## Network-free boundary

The build uses committed source data, approved local extracts, and documented desktop applications. It does not retrieve SEC filings, market data, or other analytical evidence. A local `git clone --no-hardlinks` is used; no remote fetch occurs. External-link health is a separate non-analytical release check and never feeds the model. A known SEC HTTP 403 is classified as access-restricted when the approved URL and source identity remain present, not as proof that the filing is absent.

## Commands

Generate Phase 11 records and run the clean-clone comparison:

```powershell
python -B scripts/phase11.py all
```

Run the read-only repository controls:

```powershell
python -B scripts/phase11.py validate
```

Run the complete non-mutating gate from the authoritative repository:

```powershell
python -B scripts/phase11.py verify-isolated
```

The disposable clone runs these build and validation commands in dependency order:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File scripts/validate-phase0.ps1
python -B scripts/phase1.py validate
python -B scripts/phase2.py all
python -B scripts/phase3.py validate
python -B scripts/phase4.py all
python -B scripts/phase5.py all
python -B scripts/phase6.py all
python -B scripts/phase7.py all
python -B scripts/phase8.py validate
python -B scripts/phase9.py validate
python -B scripts/phase10.py all
python -B scripts/phase10.py validate
python -B -m unittest discover -s tests -v
python -B -m unittest -v tests.test_phase8 tests.test_phase9 tests.test_phase10 tests.test_phase11
```

The isolated gate then runs both Excel PowerShell harnesses and LibreOffice against disposable workbook copies. PDF inspection and page rendering use disposable paths. The expected decision-facing outputs are `model/Quanex_Credit_Underwriting.xlsx`, `reports/credit_memo.pdf`, `reports/committee_brief.pdf`, the three PNG charts, and the phase data/document registers recorded in `ARTIFACT_MANIFEST.csv`.

## Comparison and saved scenario

Deterministic CSV, JSON, Markdown, PNG, and PDF outputs must be byte-identical. The XLSX archive may contain calculation-engine metadata differences, so the required pass criterion is the approved normalized fingerprint plus structure and scenario controls. `Assumptions!D4` must display `Base`; the workbook must retain 14 sheets, 2,902 formulas, 7 charts, zero external links, and zero cached formula errors.

## Safety and troubleshooting

- Excel and LibreOffice receive only temporary workbook copies during validation. They must never save `model/Quanex_Credit_Underwriting.xlsx` in place.
- PDF page images are written under an explicit temporary directory and removed after inspection.
- If PowerShell blocks a script, use `-ExecutionPolicy Bypass -NoProfile` for that process only.
- If Excel is absent, analytical generation can still run, but the final Excel compatibility gate is incomplete.
- If LibreOffice is absent or a different build is used, workbook canonicalization is not established for this release.
- If a bundled runtime path is unavailable, do not install an arbitrary replacement silently; document and validate the replacement first.
- If a path contains spaces, invoke commands from the repository root rather than copying absolute paths into outputs.
- `.gitattributes` must retain `*.pdf -diff -merge -text`; otherwise system Git attributes can misclassify PDF syntax.
- A workbook repair prompt, recovery log, changed formula count, non-Base saved scenario, or semantic fingerprint change is a failure.
- A clean build does not reproduce human judgment. It reproduces the owner-reviewed record and its calculations.
