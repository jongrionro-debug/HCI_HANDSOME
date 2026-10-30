"""Thin JSON/JSONL file I/O for Catalog; paths come from trusted local callers.

Example (no shared CLI entrypoint is modified)::

    with Catalog('/external/catalog.sqlite3', image_root='/external/images') as catalog:
        import_file(catalog, '/external/products.jsonl')
        export_file(catalog, '/external/products.json')

Only records are exported, not generated Maps or local database state. Importing
an export into the same catalog is idempotent; a new DB starts its own versions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

from .catalog import Catalog
from .catalog_validation import canonical, fail
from .contracts import CatalogRecord, CatalogVersions
from .errors import StyleMateError


MAX_FILE_BYTES = 16 * 1024 * 1024


def _path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        fail("catalog_file", "local JSON/JSONL file path required")
    path = Path(value)
    if path.suffix.lower() not in (".json", ".jsonl"):
        fail("catalog_file", "use a .json array or .jsonl records file")
    return path


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _parse(content: str, location: str) -> Any:
    try:
        return json.loads(content, object_pairs_hook=_object,
                          parse_constant=lambda _: fail(location, "non-finite JSON number"))
    except json.JSONDecodeError as exc:
        fail(location, f"malformed JSON at line {exc.lineno}, column {exc.colno}")
    except (ValueError, RecursionError):
        fail(location, "duplicate JSON field or excessive nesting")


def _read(path: str | Path) -> tuple[list[CatalogRecord], list[str]]:
    source = _path(path)
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                fail("catalog_file", "regular file required")
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            fail("catalog_file", "catalog input exceeds 16 MiB")
        content = data.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        fail("catalog_file", "cannot read a UTF-8 JSON/JSONL file at the configured path")
    if source.suffix.lower() == ".json":
        records = _parse(content, "JSON")
        if not isinstance(records, list):
            fail("JSON", "top-level CatalogRecord array required")
        return records, [f"JSON records[{i}]" for i in range(len(records))]
    records, locations = [], []
    for line_number, line in enumerate(content.split("\n"), 1):
        if not line.strip():
            continue
        location = f"JSONL line {line_number}"
        records.append(_parse(line, location))
        locations.append(location)
    return records, locations


def load_records(path: str | Path) -> list[CatalogRecord]:
    """Decode the file; Catalog.import_records performs contract validation."""
    return _read(path)[0]


def import_file(catalog: Catalog, path: str | Path) -> CatalogVersions:
    records, locations = _read(path)
    try:
        return catalog.import_records(records)
    except StyleMateError as exc:
        match = re.match(r"records\[(\d+)\]", exc.message)
        if match and int(match[1]) < len(locations):
            location = locations[int(match[1])]
            raise StyleMateError(exc.code, location + exc.message[match.end():]) from None
        raise


def export_file(catalog: Catalog, path: str | Path) -> None:
    """Atomic UTF-8 export; failed writes do not truncate an existing file."""
    target = _path(path)
    try:
        if catalog.db_path is not None and (target.resolve() == catalog.db_path or
                                           (target.exists() and target.samefile(catalog.db_path))):
            fail("catalog_file", "export must not overwrite the catalog database")
    except OSError:
        fail("catalog_file", "cannot resolve configured export path")
    records = catalog.export_records()
    content = (canonical(records) + "\n" if target.suffix.lower() == ".json" else
               "".join(canonical(record) + "\n" for record in records))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".lumi-catalog-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except (OSError, UnicodeError, ValueError):
        fail("catalog_file", "cannot export to the configured JSON/JSONL path")
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
