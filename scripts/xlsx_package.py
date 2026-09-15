"""Deterministically canonicalize an XLSX ZIP package.

This module normalizes package-level noise that does not change the workbook's
analytical meaning:

* ``docProps/core.xml`` uses a neutral modified timestamp of
  ``2000-01-01T00:00:00Z``;
* chart axis identifiers are reassigned in chart-path and axis-order sequence,
  with every ``axId`` and ``crossAx`` reference updated consistently; and
* ZIP members are emitted in lexical order with fixed metadata and DEFLATE
  level 9 compression.

The source is replaced atomically only after the complete candidate package
has been generated and validated.  An already canonical package is left
untouched.  This is a package reproducibility control, not a substitute for a
semantic workbook comparison or spreadsheet-engine recalculation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET


CORE_MODIFIED_TIMESTAMP = "2000-01-01T00:00:00Z"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_COMPRESSION = zipfile.ZIP_DEFLATED
ZIP_COMPRESSLEVEL = 9
AXIS_ID_BASE = 100_000_001

CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

AXIS_TAGS = {
    f"{{{CHART_NS}}}catAx",
    f"{{{CHART_NS}}}dateAx",
    f"{{{CHART_NS}}}serAx",
    f"{{{CHART_NS}}}valAx",
}
AXIS_ID_TAG = f"{{{CHART_NS}}}axId"
CROSS_AXIS_TAG = f"{{{CHART_NS}}}crossAx"
MODIFIED_TAG = f"{{{DCTERMS_NS}}}modified"


for prefix, namespace in (
    ("cp", CORE_NS),
    ("dc", "http://purl.org/dc/elements/1.1/"),
    ("dcterms", DCTERMS_NS),
    ("dcmitype", "http://purl.org/dc/dcmitype/"),
    ("xsi", XSI_NS),
    ("c", CHART_NS),
    ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"),
    ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
):
    ET.register_namespace(prefix, namespace)


class XlsxCanonicalizationError(RuntimeError):
    """Raised when an XLSX package cannot be canonicalized safely."""


@dataclass(frozen=True)
class CanonicalizationResult:
    """Summary returned by :func:`canonicalize_xlsx`."""

    path: str
    changed: bool
    sha256: str
    member_count: int
    chart_count: int
    axis_count: int
    core_modified_normalized: bool


@dataclass(frozen=True)
class _Package:
    members: dict[str, bytes]
    directory_names: frozenset[str]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
        raise XlsxCanonicalizationError(f"Unsafe XLSX member name: {name!r}")


def _load_package(payload: bytes) -> _Package:
    try:
        with zipfile.ZipFile(BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise XlsxCanonicalizationError("XLSX package contains duplicate member names")
            members: dict[str, bytes] = {}
            directories: set[str] = set()
            for info in infos:
                _validate_member_name(info.filename)
                if info.flag_bits & 0x1:
                    raise XlsxCanonicalizationError(
                        f"Encrypted XLSX member is not supported: {info.filename}"
                    )
                unix_mode = (info.external_attr >> 16) & 0o170000
                if unix_mode == stat.S_IFLNK:
                    raise XlsxCanonicalizationError(
                        f"Symbolic-link XLSX member is not supported: {info.filename}"
                    )
                data = archive.read(info)
                if info.is_dir():
                    if data:
                        raise XlsxCanonicalizationError(
                            f"Directory member contains data: {info.filename}"
                        )
                    directories.add(info.filename)
                members[info.filename] = data
            corrupt = archive.testzip()
            if corrupt is not None:
                raise XlsxCanonicalizationError(
                    f"XLSX package member failed CRC validation: {corrupt}"
                )
    except XlsxCanonicalizationError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise XlsxCanonicalizationError(f"Invalid XLSX ZIP package: {exc}") from exc
    return _Package(members, frozenset(directories))


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _normalize_core_properties(payload: bytes) -> bytes:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise XlsxCanonicalizationError(f"Malformed docProps/core.xml: {exc}") from exc
    if root.tag != f"{{{CORE_NS}}}coreProperties":
        raise XlsxCanonicalizationError("docProps/core.xml has an unexpected root element")
    modified = root.findall(f".//{MODIFIED_TAG}")
    if len(modified) > 1:
        raise XlsxCanonicalizationError(
            "docProps/core.xml contains more than one modified timestamp"
        )
    if modified:
        element = modified[0]
    else:
        element = ET.SubElement(root, MODIFIED_TAG)
        element.set(f"{{{XSI_NS}}}type", "dcterms:W3CDTF")
    element.text = CORE_MODIFIED_TIMESTAMP
    return _xml_bytes(root)


def _unsigned_axis_id(element: ET.Element, chart_path: str) -> int:
    value = element.get("val")
    try:
        parsed = int(value if value is not None else "")
    except ValueError as exc:
        raise XlsxCanonicalizationError(
            f"Chart axis identifier is not an integer in {chart_path}: {value!r}"
        ) from exc
    if not 0 <= parsed <= 0xFFFFFFFF:
        raise XlsxCanonicalizationError(
            f"Chart axis identifier is outside the unsigned 32-bit range in {chart_path}: {parsed}"
        )
    return parsed


def _normalize_chart(
    payload: bytes,
    chart_path: str,
    first_axis_id: int,
) -> tuple[bytes, int]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise XlsxCanonicalizationError(f"Malformed chart XML in {chart_path}: {exc}") from exc

    definitions: list[ET.Element] = []
    for axis in root.iter():
        if axis.tag not in AXIS_TAGS:
            continue
        identifiers = [child for child in axis if child.tag == AXIS_ID_TAG]
        if len(identifiers) != 1:
            raise XlsxCanonicalizationError(
                f"Chart axis in {chart_path} must contain exactly one axId"
            )
        definitions.append(identifiers[0])

    old_ids = [_unsigned_axis_id(element, chart_path) for element in definitions]
    if len(old_ids) != len(set(old_ids)):
        raise XlsxCanonicalizationError(
            f"Chart axis declarations are not unique in {chart_path}"
        )
    mapping = {
        old_id: first_axis_id + offset
        for offset, old_id in enumerate(old_ids)
    }
    if mapping and max(mapping.values()) > 0xFFFFFFFF:
        raise XlsxCanonicalizationError("Deterministic chart axis IDs exceed the XLSX range")

    for element in root.iter():
        if element.tag not in {AXIS_ID_TAG, CROSS_AXIS_TAG}:
            continue
        old_id = _unsigned_axis_id(element, chart_path)
        if old_id not in mapping:
            local_name = element.tag.rsplit("}", 1)[-1]
            raise XlsxCanonicalizationError(
                f"Unresolved {local_name} reference {old_id} in {chart_path}"
            )
        element.set("val", str(mapping[old_id]))

    declared = {
        _unsigned_axis_id(element, chart_path)
        for element in definitions
    }
    for element in root.iter():
        if element.tag in {AXIS_ID_TAG, CROSS_AXIS_TAG}:
            resolved = _unsigned_axis_id(element, chart_path)
            if resolved not in declared:
                raise XlsxCanonicalizationError(
                    f"Canonical chart axis reference is unresolved in {chart_path}: {resolved}"
                )
    return _xml_bytes(root), len(definitions)


def _canonical_members(package: _Package) -> tuple[dict[str, bytes], int, int, bool]:
    members = dict(package.members)
    core_normalized = "docProps/core.xml" in members
    if core_normalized:
        members["docProps/core.xml"] = _normalize_core_properties(
            members["docProps/core.xml"]
        )

    chart_paths = sorted(
        name
        for name in members
        if name.startswith("xl/charts/") and name.endswith(".xml")
    )
    next_axis_id = AXIS_ID_BASE
    total_axes = 0
    for chart_path in chart_paths:
        normalized, axis_count = _normalize_chart(
            members[chart_path], chart_path, next_axis_id
        )
        members[chart_path] = normalized
        next_axis_id += axis_count
        total_axes += axis_count
    return members, len(chart_paths), total_axes, core_normalized


def _write_package(
    destination: Path,
    members: dict[str, bytes],
    directory_names: frozenset[str],
) -> None:
    with zipfile.ZipFile(destination, "w", allowZip64=True) as archive:
        archive.comment = b""
        for name in sorted(members):
            is_directory = name in directory_names
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.create_system = 3
            info.create_version = 20
            info.extract_version = 20
            info.flag_bits = 0
            info.comment = b""
            info.extra = b""
            info.internal_attr = 0
            if is_directory:
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                archive.writestr(info, b"", compress_type=zipfile.ZIP_STORED)
            else:
                info.compress_type = ZIP_COMPRESSION
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(
                    info,
                    members[name],
                    compress_type=ZIP_COMPRESSION,
                    compresslevel=ZIP_COMPRESSLEVEL,
                )


def canonicalize_xlsx(path: str | os.PathLike[str]) -> CanonicalizationResult:
    """Canonicalize *path* atomically and return its resulting identity.

    All transformations and validation occur before ``os.replace``.  Any
    parsing, package, write, or validation failure therefore leaves the source
    bytes untouched.  If the source is already canonical, it is not replaced.
    """

    source = Path(path)
    if not source.is_file():
        raise XlsxCanonicalizationError(f"XLSX package does not exist: {source}")
    try:
        original_bytes = source.read_bytes()
        original_mode = stat.S_IMODE(source.stat().st_mode)
    except OSError as exc:
        raise XlsxCanonicalizationError(f"Unable to read XLSX package {source}: {exc}") from exc

    package = _load_package(original_bytes)
    members, chart_count, axis_count, core_normalized = _canonical_members(package)

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{source.name}.", suffix=".canonical.tmp", dir=source.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        _write_package(temporary_path, members, package.directory_names)
        # Windows requires a writable descriptor for ``fsync`` here even
        # though the ZIP writer has already closed the file.
        with temporary_path.open("rb+") as handle:
            os.fsync(handle.fileno())
        candidate_bytes = temporary_path.read_bytes()
        candidate = _load_package(candidate_bytes)
        if set(candidate.members) != set(members):
            raise XlsxCanonicalizationError(
                "Canonical XLSX package member inventory changed during repack"
            )
        if candidate.members != members:
            raise XlsxCanonicalizationError(
                "Canonical XLSX package content changed during repack"
            )
        digest = _sha256(candidate_bytes)
        if candidate_bytes == original_bytes:
            temporary_path.unlink()
            temporary_path = None
            return CanonicalizationResult(
                str(source), False, digest, len(members), chart_count,
                axis_count, core_normalized,
            )
        try:
            os.chmod(temporary_path, original_mode)
        except OSError:
            # Replacement safety does not depend on carrying filesystem mode
            # bits on platforms that do not implement POSIX permission modes.
            pass
        os.replace(temporary_path, source)
        temporary_path = None
        return CanonicalizationResult(
            str(source), True, digest, len(members), chart_count,
            axis_count, core_normalized,
        )
    except XlsxCanonicalizationError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise XlsxCanonicalizationError(
            f"Unable to create canonical XLSX package for {source}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(canonicalize_xlsx(args.workbook)), sort_keys=True))


if __name__ == "__main__":
    main()
