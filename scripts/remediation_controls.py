"""Byte-exact authorization controls for bounded post-audit remediations.

Earlier phase validators compare descendants with their original approved
checkpoints.  A remediation may intentionally change a small prior-phase set,
but a pathname-only exception would make every later mutation to that path
invisible.  These maps bind each exception to the exact reviewed bytes instead.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


PHASE2_AUTHORIZED_SHA256 = {
    "data/phase2/raw/SUPPLEMENTAL_FACTS.csv": "280f33bcfc78b56953d722f0c60a6d15a5d4c820d384954a564d5270b2b49fca",
    "data/phase2/processed/historical_spread.csv": "c0045e0c7cb204402ca98f94dbb8441daa0cd7e06221ed6e9203386f0b219fd9",
    "data/phase2/processed/historical_credit_metrics.csv": "7eff504cad848f92045da98bbece32dc30de31fa4545fb345fa6ae52219ea180",
    "data/phase2/processed/reconciliation_results.csv": "112c2cb004f7122ccee67fafac7cfdc6c9a6af3e38404814305385594c551847",
    "docs/phase-2/CREDIT_ANALYSIS.md": "576370148f1f27cab2a0f4b433cc0b03501c071bc2843f81f1f3f9f9a4ac4dbe",
    "docs/phase-2/METHODOLOGY.md": "37664bda9caa5de4abe1b181f97a734a9fc5b4ee28eef19017a9bd6c70cd2737",
    "docs/phase-2/SOURCE_LEDGER.csv": "07923d0a0720a983f4190c223470560bca7d0617a7d517de415ab8207db6162e",
    "scripts/phase2.py": "fb3e3ed9ecab167916440fd4ec831d45b8325cb07d5aea71d0fa9c6c98681f5c",
    "tests/test_phase2.py": "f46b1a5dbb3236d427a67ce31b36c8dbf0671a3a40102617e9e0ddd662f6597c",
}

PHASE6_AUTHORIZED_SHA256 = {
    "data/phase6/processed/ANALYTICAL_THRESHOLD_TESTS.csv": "ed51158042f9a34c7cbe0f6498619e8bddc7077ce963358fa978d26704d0d0d4",
    "data/phase6/processed/MONTHLY_LIQUIDITY_STRESS.csv": "1024a1fb314fd06827f7f95f4c818576529581e0464a1ef51df5c1ded3d91c11",
    "data/phase6/processed/SENSITIVITY_GRIDS.csv": "91dcb1c6a256446ba9776b4e53ad9fedfd127b71efb6bcbf25a5320dc85028fa",
    "docs/phase-6/METHODOLOGY.md": "08807d41997bab05c929da47686aa5fb721f5d3f4f80ebc818f6760282bdcf77",
    "docs/phase-6/SOURCE_LEDGER.csv": "dfeae3df3275b38f7b8f72eca0f0bbbb37f8c6016fb7332ba2b83cc759d7efa8",
}

PHASE7_AUTHORIZED_SHA256 = {
    "docs/phase-7/COVENANT_DESIGN.md": "d65dabd0afa8d017e34c612f8c2d5d8e3a84776148d5035d84600b729bf1de90",
    "data/phase7/raw/COVENANT_PROPOSALS.csv": "f280d7286a36c81221286ff14df37e22f0668afe0c8ff049194ed30f063da376",
    "data/phase7/processed/COVENANT_TEST_RESULTS.csv": "970e96cec9b029804018aeeb36a4c23316435ee375200552ec6a61323b81b10b",
    "data/phase7/processed/COVENANT_HEADROOM.csv": "a6e0a2ae04960a227ebe2933bb7a8b7cceff02e82617c6c402be252a66fee3d3",
    "data/phase7/processed/COVENANT_SUMMARY.csv": "acd3665e94b66e055ab124cd20adc5b18e210b5d1f832228627e9d4d3b9426d1",
    "data/phase7/processed/VALIDATION_RESULTS.csv": "40c05d97984688937c26a74b934dc3a0e893213476410771950c1c880667a496",
    "docs/phase-7/METHODOLOGY.md": "517c02618e1e4cc3613868941e3dd81f51477be33a850d5b1613800fc1357643",
    "docs/phase-7/SOURCE_LEDGER.csv": "814e70da33760b81ce482ec97ab7a6f5277e966cbcb8d74707abd4c953aedbe6",
}

PHASE8_AUTHORIZED_SHA256 = {
    "data/phase8/raw/MODEL_PERIOD_INPUTS.csv": "4c093d6bace56500c7923e7fef5e0c3419d331be1af585c5ff470ab5ed1f5516",
    "data/phase8/raw/STARTING_CHECKPOINT.csv": "7274425f7ec0b3ee3b3e383839e5d3f861989204ea8219cda3262a8d1091eb86",
    "data/phase8/processed/AMORTIZATION_SENSITIVITY_RESULTS.csv": "01b4b0f417fe4a2a7600df9e513bc8506b4cff232d666e183afe3660448850f1",
    "data/phase8/processed/DYNAMIC_TEST_EVIDENCE.csv": "2c3184e9fbdbf842162c3de49f02ae5ec1b34c7131260e77bf47afb9c4a7258a",
    "data/phase8/processed/FORMULA_PARITY_RESULTS.csv": "4d81ff7a250356322f8eee3a12c5d51f4561b5c41b9929671a0ae2d78ea09829",
    "data/phase8/processed/OPENING_DEBT_COMPARISON.csv": "3f69143e377e419efc6019f60e3810f8bfc133101e7d568ffb008f501f967e60",
    "data/phase8/processed/SCENARIO_CAPTURE_RESULTS.csv": "e418509b7013cbc7f9dcb84b82f2a4937f8c8eb7b4e3ce64dfc3a66ccdf79aea",
    "data/phase8/processed/TERM_SIZING_SENSITIVITY.csv": "3240a060b6661bf546c861ab523ea8768fed10f77d566629787b3ca0224a3bd8",
    "data/phase8/processed/WORKBOOK_MAP.csv": "b198a6964445fd55ea2b08c28aad9f1a29257df0de2398b5c8b7c60da63ec5fd",
    "data/phase8/processed/WORKBOOK_VALIDATION_RESULTS.csv": "deb5ad24c57abdd175fb32cefe92934e1505a3f0feaee53cc79705fc9f99cb23",
    "docs/phase-8/CALCULATION_VALIDATION.md": "ac9d6708c4008f53c3706d68eb83e35fa052bd50060cd60e7e97b9f5bf10e68b",
    "docs/phase-8/METHODOLOGY.md": "bd04c205a363a71663500b4ae391336655e7723967547c0292f5d54013c0f45b",
    "docs/phase-8/PHASE9_HANDOFF.md": "1b62e8610279fcd414c9bf9b1548ba393bcf1d800cfda41004b006b92cd9cab1",
    "docs/phase-8/SOURCE_LEDGER.csv": "2eee75eee79d319fabffedc2720037f2a985cc4efc8473be2cd5f8c897da0db5",
    "docs/phase-8/WORKBOOK_GUIDE.md": "c53c5fed390cef3d60cc74fbed53fd4e9108a841878b4a13d0760c6caae445c7",
}

PHASE9_AUTHORIZED_SHA256 = {
    "data/phase9/raw/MONITORING_TRIGGER_INPUTS.csv": "6e935adf0816a9d179d82883096a0fe7f7152209b87619677443e2621530a33a",
    "data/phase9/raw/STARTING_CHECKPOINT.csv": "e6c5d9e1f3ecfc41972a3de60b194d94a7ae6100cb15564eaa378d45048944ad",
    "data/phase9/processed/VALIDATION_RESULTS.csv": "4e8058b0af28c23add07086a9a68364a65f7e9a26228d2f9fe5a833a6e0810ac",
    "data/phase9/processed/DYNAMIC_RECOVERY_TEST_EVIDENCE.csv": "98e234686354af39844c256819d94ce2a1faf2ae063fe0acd3f16187722d8a20",
    "data/phase9/processed/MONITORING_SCHEDULE.csv": "6e935adf0816a9d179d82883096a0fe7f7152209b87619677443e2621530a33a",
    "data/phase9/processed/PHASE8_BASELINE_VERIFICATION.csv": "7fab32e3206f423611fce0b3b6c7a55f8c9b49bba6541c684d0895f0296595d4",
    "data/phase9/processed/WORKBOOK_INPUTS.json": "6aee1057b14eb8bbf359166e667c956e6e4374ac5249720db8fed5b858591ab5",
    "docs/phase-9/METHODOLOGY.md": "6a6f830dbebfcdcb8520bbf3d578bd3735f323fe5ff3144320561ec4a3bc9819",
    "docs/phase-9/MONITORING_PLAN.md": "f404102c4933451f04b73cad8ba65afc3beabe885fca51c089a85feb3d7eed7a",
    "docs/phase-9/SOURCE_LEDGER.csv": "08cdcbaddbb68f4ec29b84b4bd7b14522ef9e17344238cfbe98fd45690cfd1a0",
}

# Phase 10 may consume the reviewed prior analytical remediation, but only
# while all 45 data/document artifacts remain byte-for-byte identical to the
# stabilized dependency-ordered build.
PHASE10_PRIOR_AUTHORIZED_SHA256 = {
    **{
        path: digest
        for path, digest in PHASE2_AUTHORIZED_SHA256.items()
        if path.startswith(("data/", "docs/"))
    },
    **PHASE6_AUTHORIZED_SHA256,
    **PHASE7_AUTHORIZED_SHA256,
    **PHASE8_AUTHORIZED_SHA256,
    **PHASE9_AUTHORIZED_SHA256,
}


def exact_authorized(root: Path, relative: str, expected: dict[str, str]) -> bool:
    """Return whether *relative* exists and exactly matches its reviewed digest."""

    digest = expected.get(relative)
    path = root / relative
    return bool(
        digest
        and path.is_file()
        and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    )


def exact_authorized_paths(root: Path, expected: dict[str, str]) -> frozenset[str]:
    """Return only reviewed paths whose current bytes match their digest."""

    return frozenset(
        relative
        for relative in expected
        if exact_authorized(root, relative, expected)
    )


def unapproved_paths(
    root: Path,
    paths: list[str],
    *expected_sets: dict[str, str],
) -> list[str]:
    """Return changed/missing paths not covered by an exact reviewed digest."""

    return sorted({
        path.replace("\\", "/")
        for path in paths
        if not any(exact_authorized(root, path.replace("\\", "/"), expected)
                   for expected in expected_sets)
    })
