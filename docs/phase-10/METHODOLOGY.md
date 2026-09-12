# Phase 10 methodology

Phase 10 converts the approved Phase 0-9 record into a lender decision package without adding external evidence. The information cutoff remains **December 15, 2025** and the closing remains hypothetical at **January 31, 2026**.

The workflow reads 20 approved prior-phase artifacts, preserves their fact/calculation/term/judgment classifications, and writes 133 committee metrics with direct lineage and explicit measurement horizons. All 18 recommendation judgments are separately recorded as `owner_reviewed`. Owner review does not transform assumptions into facts or open conditions into completed diligence. Conditions remain separated into conditions precedent, ongoing covenants, monitoring requirements, analyst warnings, and unresolved diligence.

The memo and brief are generated from the same registers as the workbook summary. The system Python orchestrates data and validation; the bundled Python 3.12 runtime supplies ReportLab 4.4.9 and Pillow 12.3.0 for PDF/chart rendering. The existing artifact-tool and LibreOffice/Excel validation chain is retained for the workbook. No live network access is used.

The repository-root `.gitattributes` classifies PDF deliverables as binary with `*.pdf -diff -merge -text`. This portable repository rule prevents system-level text-conversion attributes from treating valid PDF object and cross-reference syntax as text while preserving ordinary whitespace checks for source and data files.

The July 31, 2029 common-horizon comparison uses total funded debt: $495.368m existing, $507.954m reference, and $514.754m selected. Ultimate gaps use bank debt and their contractual dates: $432.749m existing at August 1, 2029 and $340.948m reference / $324.780m selected at January 31, 2031. These measures are never conflated. Recovery methods remain alternatives. Official recovery and opening cash-interest coverage remain `N/D`. The decision remains a hypothetical public-information project recommendation, not an actual bank approval or commitment.
