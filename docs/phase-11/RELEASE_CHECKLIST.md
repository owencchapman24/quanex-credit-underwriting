# Release checklist

## Technical gate

- [x] Approved Phase 10 lineage and artifact anchors recorded.
- [x] Network-free local-clone reproduction implemented.
- [x] Exact comparison required for deterministic text, data, chart, and PDF outputs.
- [x] Normalized semantic comparison required for the workbook.
- [x] Excel, LibreOffice, and PDF checks use disposable copies or paths.
- [x] README links, artifact existence, hashes, page counts, and workbook structure are controlled.
- [x] Credential, local-path, residue, cutoff, source-lineage, whitespace, and repository-attribute checks are implemented.
- [x] Phase 12 implementation is excluded.

## Licensing and redistribution

No `LICENSE`, `COPYING`, or equivalent license file exists. The public repository is therefore legally unlicensed/all-rights-reserved by default. Technical validation may proceed, but publication under a reusable license is an explicit owner decision before final release.

A practical owner decision is to license original code separately from narrative reports and curated data. A permissive code license such as MIT or Apache-2.0 may suit original scripts, while reports and data may remain all-rights-reserved or use a separate content license after reviewing source attribution, public-filing extracts, logos, charts, and redistribution constraints. Public availability of third-party source material does not itself grant a right to relicense it. The repository preserves bounded extracts and provenance rather than copying complete third-party documents.

## Owner-review gate before Phase 12

- [x] AI-use disclosure reviewed and approved by the owner (`owner_reviewed`).
- [ ] Choose the code, report, and data licensing treatment.
- [ ] Confirm public repository visibility and redistribution comfort.
- [ ] Review Phase 11 reproducibility and release-QA results.
- [ ] Preserve Conditional Approval, all open conditions, and the mandatory fallback.
