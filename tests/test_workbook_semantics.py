from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workbook_semantics import semantic_workbook_fingerprint  # noqa: E402


SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1"><c r="A1" t="s"><v>{index}</v></c></row></sheetData>
</worksheet>"""
STRINGS = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
  <si><t>{first}</t></si><si><t>{second}</t></si>
</sst>"""
DRAWING = """<?xml version="1.0" encoding="UTF-8"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <xdr:twoCellAnchor{edit_as}><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
 <xdr:to><xdr:col>{to_col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>10</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
 <xdr:graphicFrame><xdr:nvGraphicFramePr><xdr:cNvPr id="2" name="Credit chart"/></xdr:nvGraphicFramePr><a:graphic><a:graphicData><c:chart r:id="{first_rel}"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>
 </xdr:twoCellAnchor>
 <xdr:twoCellAnchor editAs="twoCell"><xdr:from><xdr:col>8</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
 <xdr:to><xdr:col>12</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>10</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
 <xdr:graphicFrame><xdr:nvGraphicFramePr><xdr:cNvPr id="3" name="Liquidity chart"/></xdr:nvGraphicFramePr><a:graphic><a:graphicData><c:chart r:id="{second_rel}"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>
 </xdr:twoCellAnchor></xdr:wsDr>"""
RELATIONSHIPS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="{first_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
 <Relationship Id="{second_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart2.xml"/>
</Relationships>"""
CHART = """<?xml version="1.0" encoding="UTF-8"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">
 <c:chart><c:plotArea><c:lineChart><c:axId val="{first}"/><c:axId val="{second}"/></c:lineChart>
 <c:catAx><c:axId val="{first}"/><c:crossAx val="{second}"/></c:catAx>
 <c:valAx><c:axId val="{second}"/><c:crossAx val="{first}"/></c:valAx></c:plotArea></c:chart>
</c:chartSpace>"""
CHART_STRUCTURAL_VARIANT = """<?xml version='1.0' encoding='UTF-8'?>
<chartSpace xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><chart><plotArea>
<lineChart><axId val='{first}'></axId><axId val='{second}'></axId></lineChart>
<catAx><axId val='{first}'></axId><crossAx val='{second}'></crossAx></catAx>
<valAx><axId val='{second}'></axId><crossAx val='{first}'></crossAx></valAx>
</plotArea></chart></chartSpace>"""


def make_book(
    path: Path,
    *,
    text: str = "USD millions",
    reverse: bool = False,
    col: int = 1,
    to_col: int = 5,
    axis_ids: tuple[int, int] = (1234, 5678),
    relationship_ids: tuple[str, str] = ("rId1", "rId2"),
    swap_chart_relationships: bool = False,
    edit_as: str | None = None,
    structural_chart_variant: bool = False,
) -> None:
    first, second, index = ("unused", text, 1) if not reverse else (text, "unused", 0)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", STRINGS.format(first=first, second=second))
        archive.writestr("xl/worksheets/sheet1.xml", SHEET.format(index=index))
        archive.writestr(
            "xl/drawings/drawing1.xml",
            DRAWING.format(
                col=col,
                to_col=to_col,
                edit_as="" if edit_as is None else f' editAs="{edit_as}"',
                first_rel=(
                    relationship_ids[1]
                    if swap_chart_relationships
                    else relationship_ids[0]
                ),
                second_rel=(
                    relationship_ids[0]
                    if swap_chart_relationships
                    else relationship_ids[1]
                ),
            ),
        )
        archive.writestr(
            "xl/drawings/_rels/drawing1.xml.rels",
            RELATIONSHIPS.format(
                first_id=relationship_ids[0], second_id=relationship_ids[1]
            ),
        )
        archive.writestr(
            "xl/charts/chart1.xml",
            (
                CHART_STRUCTURAL_VARIANT if structural_chart_variant else CHART
            ).format(first=axis_ids[0], second=axis_ids[1]),
        )
        archive.writestr(
            "xl/charts/chart2.xml",
            CHART.format(first=2468, second=1357),
        )


class WorkbookSemanticFingerprintTests(unittest.TestCase):
    def test_shared_string_label_change_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, text="USD millions")
            make_book(right, text="USD thousands")
            self.assertNotEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_semantically_equivalent_shared_string_reindex_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, reverse=False)
            make_book(right, reverse=True)
            self.assertEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_meaningful_drawing_move_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, col=1)
            make_book(right, col=20)
            self.assertNotEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_meaningful_drawing_resize_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, to_col=5)
            make_book(right, to_col=12)
            self.assertNotEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_equivalent_chart_axis_id_renumbering_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, axis_ids=(1234, 5678))
            make_book(right, axis_ids=(9911, 7722))
            self.assertEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_axis_id_normalization_is_structural_not_serialization_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, axis_ids=(1234, 5678))
            make_book(
                right,
                axis_ids=(9911, 7722),
                structural_chart_variant=True,
            )
            self.assertEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_chart_relationship_swap_between_anchors_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left)
            make_book(right, swap_chart_relationships=True)
            self.assertNotEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_semantically_equivalent_relationship_id_renumbering_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, relationship_ids=("rId1", "rId2"))
            make_book(right, relationship_ids=("rId19", "rId4"))
            self.assertEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_meaningful_anchor_edit_as_change_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, edit_as="twoCell")
            make_book(right, edit_as="oneCell")
            self.assertNotEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )

    def test_implicit_and_explicit_default_edit_as_compare_equal(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / "left.xlsx", Path(folder) / "right.xlsx"
            make_book(left, edit_as=None)
            make_book(right, edit_as="twoCell")
            self.assertEqual(
                semantic_workbook_fingerprint(left), semantic_workbook_fingerprint(right)
            )


if __name__ == "__main__":
    unittest.main()
