"""Tests for deterministic, fail-safe XLSX package canonicalization."""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import xlsx_package  # noqa: E402


CHART_NS = xlsx_package.CHART_NS
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def core_properties(modified: str) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="{xlsx_package.CORE_NS}" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="{xlsx_package.DCTERMS_NS}" xmlns:xsi="{xlsx_package.XSI_NS}">
  <dc:creator>Quanex test</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">2025-12-15T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified>
</cp:coreProperties>'''.encode("utf-8")


def chart_xml(first_axis: int, second_axis: int, label: str, *, unresolved_cross: bool = False) -> bytes:
    cross = 4_294_000_000 if unresolved_cross else second_axis
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="{CHART_NS}" xmlns:a="{DRAWINGML_NS}" xmlns:r="{REL_NS}">
  <c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>{label}</a:t></a:r></a:p></c:rich></c:tx></c:title>
    <c:plotArea>
      <c:lineChart><c:axId val="{first_axis}"/><c:axId val="{second_axis}"/></c:lineChart>
      <c:catAx><c:axId val="{first_axis}"/><c:crossAx val="{cross}"/></c:catAx>
      <c:valAx><c:axId val="{second_axis}"/><c:crossAx val="{first_axis}"/></c:valAx>
    </c:plotArea>
  </c:chart>
</c:chartSpace>'''.encode("utf-8")


def drawing_xml(column_offset: int) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="{DRAWING_NS}" xmlns:a="{DRAWINGML_NS}">
  <xdr:twoCellAnchor>
    <xdr:from><xdr:col>2</xdr:col><xdr:colOff>{column_offset}</xdr:colOff><xdr:row>4</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:to><xdr:col>10</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>20</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
  </xdr:twoCellAnchor>
</xdr:wsDr>'''.encode("utf-8")


def synthetic_members(
    *,
    modified: str,
    axis_seed: int,
    label: str = "Liquidity",
    column_offset: int = 100,
    unresolved_cross: bool = False,
) -> dict[str, bytes]:
    return {
        "[Content_Types].xml": b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>''',
        "_rels/.rels": b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>''',
        "docProps/core.xml": core_properties(modified),
        "xl/charts/chart1.xml": chart_xml(
            axis_seed + 1,
            axis_seed + 2,
            label,
            unresolved_cross=unresolved_cross,
        ),
        # Deliberately reuse the source IDs in another chart.  Canonical IDs
        # must be unique across the complete package, not only within a chart.
        "xl/charts/chart2.xml": chart_xml(axis_seed + 1, axis_seed + 2, "Leverage"),
        "xl/drawings/drawing1.xml": drawing_xml(column_offset),
    }


def write_synthetic_package(
    path: Path,
    members: dict[str, bytes],
    *,
    variant: int,
) -> None:
    names = sorted(members, reverse=bool(variant % 2))
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = f"nondeterministic archive comment {variant}".encode("ascii")
        for index, name in enumerate(names):
            info = zipfile.ZipInfo(
                name,
                (2024 + variant, 1 + (index % 10), 1 + (index % 20), 12, 0, 0),
            )
            info.create_system = variant % 2
            info.external_attr = ((stat.S_IFREG | 0o644) << 16) + variant
            info.comment = f"member {variant}-{index}".encode("ascii")
            # A valid, empty private extra field whose bytes differ by variant.
            info.extra = bytes((variant, 0xCA, 0, 0))
            compression = zipfile.ZIP_STORED if (variant + index) % 2 else zipfile.ZIP_DEFLATED
            archive.writestr(info, members[name], compress_type=compression)


class XlsxPackageCanonicalizationTests(unittest.TestCase):
    def test_varying_timestamp_axis_ids_and_zip_metadata_yield_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-xlsx-canonical-") as directory:
            root = Path(directory)
            first = root / "first.xlsx"
            second = root / "second.xlsx"
            write_synthetic_package(
                first,
                synthetic_members(modified="2026-09-14T12:00:01Z", axis_seed=100),
                variant=1,
            )
            write_synthetic_package(
                second,
                synthetic_members(modified="2035-01-02T03:04:05Z", axis_seed=900),
                variant=2,
            )

            first_result = xlsx_package.canonicalize_xlsx(first)
            second_result = xlsx_package.canonicalize_xlsx(second)

            self.assertTrue(first_result.changed)
            self.assertTrue(second_result.changed)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_result.sha256, second_result.sha256)
            self.assertEqual(first_result.chart_count, 2)
            self.assertEqual(first_result.axis_count, 4)

            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), sorted(archive.namelist()))
                self.assertEqual(archive.comment, b"")
                for info in archive.infolist():
                    self.assertEqual(info.date_time, xlsx_package.ZIP_TIMESTAMP)
                    self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)
                    self.assertEqual(info.comment, b"")
                    self.assertEqual(info.extra, b"")
                core = ET.fromstring(archive.read("docProps/core.xml"))
                self.assertEqual(
                    core.find(xlsx_package.MODIFIED_TAG).text,
                    xlsx_package.CORE_MODIFIED_TIMESTAMP,
                )

    def test_chart_axis_ids_are_unique_stable_and_references_remain_consistent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-xlsx-axes-") as directory:
            workbook = Path(directory) / "axes.xlsx"
            write_synthetic_package(
                workbook,
                synthetic_members(modified="2026-01-01T00:00:00Z", axis_seed=500),
                variant=1,
            )
            xlsx_package.canonicalize_xlsx(workbook)

            all_declared: list[int] = []
            with zipfile.ZipFile(workbook) as archive:
                for chart_path in ("xl/charts/chart1.xml", "xl/charts/chart2.xml"):
                    chart = ET.fromstring(archive.read(chart_path))
                    declared = []
                    for axis in chart.iter():
                        if axis.tag in xlsx_package.AXIS_TAGS:
                            identifier = next(child for child in axis if child.tag == xlsx_package.AXIS_ID_TAG)
                            declared.append(int(identifier.get("val")))
                    referenced = [
                        int(element.get("val"))
                        for element in chart.iter()
                        if element.tag in {xlsx_package.AXIS_ID_TAG, xlsx_package.CROSS_AXIS_TAG}
                    ]
                    self.assertEqual(len(declared), len(set(declared)))
                    self.assertLessEqual(set(referenced), set(declared))
                    all_declared.extend(declared)

            self.assertEqual(
                all_declared,
                list(range(xlsx_package.AXIS_ID_BASE, xlsx_package.AXIS_ID_BASE + 4)),
            )
            self.assertEqual(len(all_declared), len(set(all_declared)))

    def test_labels_and_drawing_geometry_remain_semantically_distinct(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-xlsx-semantics-") as directory:
            root = Path(directory)
            baseline = root / "baseline.xlsx"
            changed_label = root / "changed-label.xlsx"
            changed_geometry = root / "changed-geometry.xlsx"
            write_synthetic_package(
                baseline,
                synthetic_members(modified="2026-01-01T00:00:00Z", axis_seed=1),
                variant=1,
            )
            write_synthetic_package(
                changed_label,
                synthetic_members(
                    modified="2030-01-01T00:00:00Z",
                    axis_seed=1000,
                    label="Liquidity headroom",
                ),
                variant=2,
            )
            write_synthetic_package(
                changed_geometry,
                synthetic_members(
                    modified="2030-01-01T00:00:00Z",
                    axis_seed=1000,
                    column_offset=999_999,
                ),
                variant=2,
            )
            for workbook in (baseline, changed_label, changed_geometry):
                xlsx_package.canonicalize_xlsx(workbook)

            self.assertNotEqual(baseline.read_bytes(), changed_label.read_bytes())
            self.assertNotEqual(baseline.read_bytes(), changed_geometry.read_bytes())
            with zipfile.ZipFile(changed_label) as archive:
                self.assertIn(b"Liquidity headroom", archive.read("xl/charts/chart1.xml"))
            with zipfile.ZipFile(changed_geometry) as archive:
                self.assertIn(b"999999", archive.read("xl/drawings/drawing1.xml"))

    def test_canonicalization_is_idempotent_and_does_not_replace_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-xlsx-idempotent-") as directory:
            workbook = Path(directory) / "idempotent.xlsx"
            write_synthetic_package(
                workbook,
                synthetic_members(modified="2040-01-01T00:00:00Z", axis_seed=42),
                variant=1,
            )
            first_result = xlsx_package.canonicalize_xlsx(workbook)
            first_bytes = workbook.read_bytes()
            first_mtime = workbook.stat().st_mtime_ns
            second_result = xlsx_package.canonicalize_xlsx(workbook)

            self.assertTrue(first_result.changed)
            self.assertFalse(second_result.changed)
            self.assertEqual(workbook.read_bytes(), first_bytes)
            self.assertEqual(workbook.stat().st_mtime_ns, first_mtime)
            self.assertEqual(first_result.sha256, second_result.sha256)

    def test_malformed_zip_fails_without_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-xlsx-malformed-") as directory:
            workbook = Path(directory) / "broken.xlsx"
            workbook.write_bytes(b"not an OOXML ZIP package")
            before = workbook.read_bytes()

            with self.assertRaises(xlsx_package.XlsxCanonicalizationError):
                xlsx_package.canonicalize_xlsx(workbook)

            self.assertEqual(workbook.read_bytes(), before)
            self.assertFalse(list(workbook.parent.glob(f".{workbook.name}.*.canonical.tmp")))

    def test_unresolved_chart_reference_fails_without_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quanex-xlsx-bad-chart-") as directory:
            workbook = Path(directory) / "bad-chart.xlsx"
            write_synthetic_package(
                workbook,
                synthetic_members(
                    modified="2026-01-01T00:00:00Z",
                    axis_seed=10,
                    unresolved_cross=True,
                ),
                variant=1,
            )
            before = workbook.read_bytes()

            with self.assertRaises(xlsx_package.XlsxCanonicalizationError):
                xlsx_package.canonicalize_xlsx(workbook)

            self.assertEqual(workbook.read_bytes(), before)
            self.assertFalse(list(workbook.parent.glob(f".{workbook.name}.*.canonical.tmp")))


if __name__ == "__main__":
    unittest.main()
