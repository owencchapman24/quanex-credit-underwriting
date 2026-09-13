# Phase 11 methodology

Phase 11 is a release-quality layer over the approved Phase 0-10 underwriting record. It adds no analytical evidence and changes no recommendation, structure, assumption, scenario, covenant, or recovery conclusion. The information cutoff remains December 15, 2025 and the closing remains hypothetical at January 31, 2026.

The workflow inventories the software actually used, resolves internal repository links, hashes decision-facing artifacts, verifies cross-deliverable anchors, and rebuilds approved outputs in a disposable local clone. CSV, JSON, Markdown, PNG, and PDF artifacts are compared byte-for-byte after reproduction. The workbook is compared by its approved normalized analytical fingerprint and by sheet order, formulas, values, formats, charts, data validation, names, calculation settings, scenario captures, and saved Base scenario. Raw XLSX ZIP identity is recorded but is not the semantic pass criterion because calculation engines can rewrite non-analytical metadata.

`python -B scripts/phase11.py all` writes only `data/phase11/processed` and `docs/phase-11/SOURCE_LEDGER.csv`. It performs the write-producing build in a disposable clone. `validate` is read-only. `verify-isolated` creates another disposable clone, overlays the current Phase 11 review files, makes a temporary local verification commit, executes the complete release gate there, removes the clone, and compares the authoritative repository manifest and Git status before and after.

Release QA distinguishes mechanical reproducibility from human judgment. Debt-document interpretation, EBITDA adjustments, scenario severity, accessible cash, facility sizing, covenant design, recovery limits, and the Conditional Approval recommendation remain owner-reviewed judgments; a successful build does not re-approve them.

The AI-use and analytical-ownership disclosure is `owner_reviewed`; licensing remains a separate pending owner decision and is not a technical validation failure.

Phase 11 includes no Phase 12 interview narrative or final-release action.
