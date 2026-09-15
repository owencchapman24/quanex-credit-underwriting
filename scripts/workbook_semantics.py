"""Deterministic semantic hashing for the underwriting XLSX artifact.

The digest resolves shared-string references and records meaningful drawing
placement while continuing to ignore ZIP packaging, calculation-chain, and
core-property noise.  It is a comparison control, not a substitute for engine
recalculation, formula checks, rendered review, or the separate raw SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EMU_PER_POINT = 12_700
EXCLUDED_PARTS = {"docProps/core.xml", "xl/calcChain.xml", "xl/sharedStrings.xml"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def _resolved_worksheet(data: bytes, strings: list[str]) -> bytes:
    root = ET.fromstring(data)
    for cell in root.iter(f"{{{MAIN_NS}}}c"):
        if cell.attrib.get("t") != "s":
            continue
        value = cell.find(f"{{{MAIN_NS}}}v")
        raw_index = "" if value is None else (value.text or "")
        try:
            resolved = strings[int(raw_index)]
        except (IndexError, TypeError, ValueError):
            resolved = f"#INVALID_SHARED_STRING_INDEX:{raw_index}"
        cell.set("t", "str")
        if value is None:
            value = ET.SubElement(cell, f"{{{MAIN_NS}}}v")
        value.text = resolved
    return ET.tostring(root, encoding="utf-8")


def _quantized_emu(text: str | None) -> int | None:
    if text in (None, ""):
        return None
    value = int(text)
    if value >= 0:
        return (value + EMU_PER_POINT // 2) // EMU_PER_POINT
    return -((-value + EMU_PER_POINT // 2) // EMU_PER_POINT)


def _child_text(parent: ET.Element, local_name: str) -> str | None:
    node = next((item for item in parent if _local(item.tag) == local_name), None)
    return None if node is None else node.text


def _marker(parent: ET.Element | None) -> dict[str, int | None] | None:
    if parent is None:
        return None
    return {
        "col": int(_child_text(parent, "col") or 0),
        "col_offset_points": _quantized_emu(_child_text(parent, "colOff")),
        "row": int(_child_text(parent, "row") or 0),
        "row_offset_points": _quantized_emu(_child_text(parent, "rowOff")),
    }


def _drawing_relationships(
    data: bytes,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """Resolve package-local relationship IDs without treating IDs as meaning.

    Relationship identifiers are ZIP-serialization details.  A canonical ID is
    assigned from the relationship's type, target, and target mode so a
    consistent rId renumbering compares equal while a chart-to-anchor swap does
    not.  Duplicate semantic relationships deliberately share a canonical ID;
    the returned summary retains duplicate rows so relationship multiplicity is
    still part of the fingerprint.
    """

    root = ET.fromstring(data)
    entries: list[dict[str, str]] = []
    for node in root:
        if _local(node.tag) != "Relationship":
            continue
        entries.append({
            "raw_id": node.attrib.get("Id", "#MISSING_RELATIONSHIP_ID"),
            "target": node.attrib.get("Target", "#MISSING_RELATIONSHIP_TARGET"),
            "type": node.attrib.get("Type", "#MISSING_RELATIONSHIP_TYPE"),
            "target_mode": node.attrib.get("TargetMode", "Internal"),
        })

    signatures = sorted({
        (entry["type"], entry["target"], entry["target_mode"])
        for entry in entries
    })
    canonical_ids = {
        signature: f"relationship_{sequence}"
        for sequence, signature in enumerate(signatures, 1)
    }
    by_id: dict[str, dict[str, str]] = {}
    summary: list[dict[str, str]] = []
    for entry in entries:
        signature = (entry["type"], entry["target"], entry["target_mode"])
        normalized = {
            "relationship_id": canonical_ids[signature],
            "target": entry["target"],
            "type": entry["type"],
            "target_mode": entry["target_mode"],
        }
        by_id[entry["raw_id"]] = normalized
        summary.append(normalized)
    summary.sort(key=lambda item: (
        item["relationship_id"], item["type"], item["target"], item["target_mode"]
    ))
    return by_id, summary


def _drawing_relationship_part(drawing_part: str) -> str:
    path = PurePosixPath(drawing_part)
    return str(path.parent / "_rels" / f"{path.name}.rels")


def _relationship_references(
    element: ET.Element,
    relationships: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    relationship_prefix = f"{{{OFFICE_REL_NS}}}"
    for node in element.iter():
        for attribute, raw_id in node.attrib.items():
            if not attribute.startswith(relationship_prefix):
                continue
            resolved = relationships.get(raw_id)
            if resolved is None:
                references.append({
                    "attribute": _local(attribute),
                    "relationship_id": f"unresolved:{raw_id}",
                    "target": "#UNRESOLVED_RELATIONSHIP_TARGET",
                    "type": "#UNRESOLVED_RELATIONSHIP_TYPE",
                    "target_mode": "#UNRESOLVED_RELATIONSHIP_MODE",
                })
            else:
                references.append({
                    "attribute": _local(attribute),
                    **resolved,
                })
    references.sort(key=lambda item: (
        item["attribute"], item["relationship_id"], item["type"],
        item["target"], item["target_mode"]
    ))
    return references


def drawing_geometry(
    data: bytes,
    relationships: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    """Return stable, meaningful placement/size records for a drawing part.

    Offsets and extents are rounded to whole points to tolerate sub-point
    serialization drift while retaining cell anchors and meaningful movement.
    """

    root = ET.fromstring(data)
    relationships = relationships or {}
    records: list[dict[str, object]] = []
    for sequence, anchor in enumerate(root, 1):
        anchor_type = _local(anchor.tag)
        if anchor_type not in {"twoCellAnchor", "oneCellAnchor", "absoluteAnchor"}:
            continue
        children = {_local(child.tag): child for child in anchor}
        objects = [
            child for child in anchor
            if _local(child.tag) in {"graphicFrame", "pic", "sp", "cxnSp", "grpSp"}
        ]
        names: list[str] = []
        for obj in objects:
            for node in obj.iter():
                if _local(node.tag) == "cNvPr" and node.attrib.get("name"):
                    names.append(node.attrib["name"])
        extent = children.get("ext")
        position = children.get("pos")
        records.append({
            "sequence": sequence,
            "anchor_type": anchor_type,
            "edit_as": (
                anchor.attrib.get("editAs", "twoCell")
                if anchor_type == "twoCellAnchor"
                else anchor.attrib.get("editAs")
            ),
            "from": _marker(children.get("from")),
            "to": _marker(children.get("to")),
            "absolute_position_points": None if position is None else {
                "x": _quantized_emu(position.attrib.get("x")),
                "y": _quantized_emu(position.attrib.get("y")),
            },
            "extent_points": None if extent is None else {
                "cx": _quantized_emu(extent.attrib.get("cx")),
                "cy": _quantized_emu(extent.attrib.get("cy")),
            },
            "object_types": [_local(item.tag) for item in objects],
            "object_names": names,
            "relationship_references": _relationship_references(
                anchor, relationships
            ),
        })
    return records


def _normalized_chart(data: bytes) -> bytes:
    """Normalize chart axis identifiers through parsed XML structure.

    Axis identifiers are application-generated cross-reference keys, not
    analytical content.  Parsing avoids dependence on namespace prefixes,
    attribute quoting, empty-element spelling, or pretty-print whitespace.
    """

    root = ET.fromstring(data)
    axis_ids: dict[str, str] = {}
    for node in root.iter():
        if _local(node.tag) not in {"axId", "crossAx"} or "val" not in node.attrib:
            continue
        original = node.attrib["val"]
        axis_ids.setdefault(original, str(len(axis_ids) + 1))
        node.set("val", axis_ids[original])

    # Remove indentation-only nodes before canonicalization but retain all
    # meaningful chart text, including leading/trailing spaces.
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    serialized = ET.tostring(root, encoding="unicode")
    return ET.canonicalize(serialized, rewrite_prefixes=True).encode("utf-8")


def semantic_workbook_fingerprint(
    workbook: Path,
    *,
    prefix_parts: Iterable[bytes] = (),
) -> str:
    """Hash analytical workbook content with bounded semantic normalization."""

    digest = hashlib.sha256()
    for part in prefix_parts:
        digest.update(part)
    with zipfile.ZipFile(workbook) as archive:
        strings = _shared_strings(archive)
        for name in sorted(archive.namelist()):
            if name in EXCLUDED_PARTS:
                continue
            data = archive.read(name)
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                data = _resolved_worksheet(data, strings)
            elif name.startswith("xl/drawings/drawing") and name.endswith(".xml"):
                relationship_part = _drawing_relationship_part(name)
                relationships: dict[str, dict[str, str]] = {}
                if relationship_part in archive.namelist():
                    relationships, _ = _drawing_relationships(
                        archive.read(relationship_part)
                    )
                data = json.dumps(
                    drawing_geometry(data, relationships),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            elif (
                name.startswith("xl/drawings/_rels/drawing")
                and name.endswith(".xml.rels")
            ):
                _, relationship_summary = _drawing_relationships(data)
                data = json.dumps(
                    relationship_summary, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            elif (
                name.startswith("xl/charts/chart")
                or name.startswith("xl/drawings/charts/chart")
            ) and name.endswith(".xml"):
                data = _normalized_chart(data)
            digest.update(name.encode("utf-8"))
            digest.update(data)
    return digest.hexdigest()
