"""Offline supplier catalog storage, independent of the user memory database.

No product maps are generated here. Unbuilt/stale maps cannot be requested as
fresh dependencies. Import receipts include only already-current maps in
``products``; raw records/versions remain accessible before mapping via
``get_record``/``raw_version``. This avoids inventing a map version zero.

Image freshness follows supplied revisions/hashes, not remote byte inspection.
Remote images resolve only for explicitly allowed supplier hosts and are never
fetched. Local display uses configured-root, bounded raster reads only.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Iterator
from urllib.parse import urlsplit

from .catalog_validation import (
    IMAGE_TYPES, MAX_RECORD_BYTES, canonical, fail, fields, identifier,
    validate_assertions, validate_record, version,
)
from .contracts import (
    CATALOG_FORMAT_VERSION, V1_REGISTRY_VERSION, CatalogRecord, CatalogVersions,
    ImageSource, ProductMap, RegistryPort,
)
from .errors import StyleMateError
from .registry import load_registry


MAX_IMAGE_BYTES = 10 * 1024 * 1024


class Catalog:
    def __init__(self, db_path: str | Path, *, image_root: str | Path | None = None,
                 allowed_image_hosts: tuple[str, ...] = (), registry: RegistryPort | None = None) -> None:
        for name, value in (("catalog_db", db_path), ("image_root", image_root)):
            if value is None and name == "image_root":
                continue
            if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
                fail(name, "configured local path required")
        if not isinstance(allowed_image_hosts, tuple) or any(not isinstance(host, str) for host in allowed_image_hosts):
            fail("allowed_image_hosts", "tuple of exact supplier DNS hostnames required")
        self.registry = registry if registry is not None else load_registry(V1_REGISTRY_VERSION)
        if self.registry.version != V1_REGISTRY_VERSION:
            fail("registry", "unsupported catalog registry", "unsupported_contract")
        try:
            self.db_path = Path(db_path).resolve() if str(db_path) != ":memory:" else None
            self.image_root = Path(image_root).resolve() if image_root is not None else None
        except (OSError, ValueError, RuntimeError):
            fail("catalog_paths", "cannot resolve configured local paths")
        self.allowed_image_hosts = frozenset(host.lower() for host in allowed_image_hosts)
        for host in self.allowed_image_hosts:
            # The trusted caller supplies DNS hostnames, never URL/path patterns.
            if (not isinstance(host, str) or "." not in host or
                    any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-." for c in host)
                    or host.endswith(".local") or all(c in "0123456789." for c in host)):
                fail("allowed_image_hosts", "exact supplier DNS hostnames required")
        self._db: sqlite3.Connection
        try:
            self._db = sqlite3.connect(str(db_path))
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys=ON")
            tables = {row[0] for row in self._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables and tables != {"catalog_meta", "catalog_products", "catalog_images"}:
                fail("catalog_db", "use a separate catalog database", "unsupported_contract")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS catalog_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    format_version TEXT NOT NULL,
                    catalog_version INTEGER NOT NULL CHECK(catalog_version>=0)
                );
                CREATE TABLE IF NOT EXISTS catalog_products (
                    product_id TEXT PRIMARY KEY, record_json TEXT NOT NULL,
                    raw_version INTEGER NOT NULL CHECK(raw_version>0),
                    map_version INTEGER, map_json TEXT
                );
                CREATE TABLE IF NOT EXISTS catalog_images (
                    image_id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL REFERENCES catalog_products(product_id),
                    version INTEGER NOT NULL CHECK(version>0), source_json TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1))
                );
            """)
            self._db.execute("INSERT OR IGNORE INTO catalog_meta VALUES (1,?,0)", (CATALOG_FORMAT_VERSION,))
            if self._db.execute("SELECT format_version FROM catalog_meta WHERE singleton=1").fetchone()[0] != CATALOG_FORMAT_VERSION:
                fail("catalog_db", "unsupported catalog database format", "unsupported_contract")
            self._db.commit()
        except (sqlite3.Error, OSError, ValueError, StyleMateError) as exc:
            if hasattr(self, "_db"):
                self._db.close()
            if isinstance(exc, StyleMateError):
                raise
            fail("catalog_db", "cannot open configured catalog database")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Catalog:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        try:
            self._db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def _product(self, product_id: str) -> sqlite3.Row:
        identifier(product_id, "product_id")
        row = self._db.execute("SELECT * FROM catalog_products WHERE product_id=?", (product_id,)).fetchone()
        if row is None:
            fail("product_id", "product not found", "not_found")
        return row

    def _image(self, image_id: str) -> sqlite3.Row:
        identifier(image_id, "image_id")
        row = self._db.execute("SELECT * FROM catalog_images WHERE image_id=? AND active=1", (image_id,)).fetchone()
        if row is None:
            fail("image_id", "image reference is unavailable", "not_found")
        return row

    def _check_local_root(self, source: ImageSource, location: str) -> None:
        if source["kind"] == "local" and self.image_root is not None:
            try:
                candidate = (self.image_root / source["location"]).resolve()
                if not candidate.is_relative_to(self.image_root):
                    raise ValueError
            except (ValueError, OSError, RuntimeError):
                fail(location, "image path/symlink escapes the configured root")

    def import_records(self, records: list[CatalogRecord]) -> CatalogVersions:
        if not isinstance(records, list):
            fail("records", "CatalogRecord array required")
        prepared = []
        products, images = set(), set()
        for index, record in enumerate(records):
            at = f"records[{index}]"
            item = validate_record(record, self.registry, at)
            if item["product_id"] in products:
                fail(f"{at}.product_id", "duplicate product ID in this import", "catalog_conflict")
            products.add(item["product_id"])
            for i, image in enumerate(item["images"]):
                if image["image_id"] in images:
                    fail(f"{at}.images[{i}].image_id", "image ID belongs to multiple products", "catalog_conflict")
                images.add(image["image_id"])
                self._check_local_root(image, f"{at}.images[{i}].location")
            prepared.append(item)

        with self._transaction(write=True):
            changed = False
            for index, item in enumerate(prepared):
                product_id = item["product_id"]
                old = self._db.execute("SELECT * FROM catalog_products WHERE product_id=?", (product_id,)).fetchone()
                old_record = json.loads(old["record_json"]) if old else None
                if old:
                    if any(old_record["source"][key] != item["source"][key] for key in ("source_id", "url")):
                        fail(f"records[{index}].source", "product ID has a different source identity", "catalog_conflict")
                    raw_changed = canonical({k: v for k, v in old_record.items() if k != "images"}) != canonical(
                        {k: v for k, v in item.items() if k != "images"})
                    if canonical(old_record) != canonical(item):
                        self._db.execute("UPDATE catalog_products SET record_json=?,raw_version=? WHERE product_id=?",
                                         (canonical(item), old["raw_version"] + int(raw_changed), product_id))
                        changed = True
                else:
                    self._db.execute("INSERT INTO catalog_products VALUES (?,?,1,NULL,NULL)",
                                     (product_id, canonical(item)))
                    changed = True
                current_ids = {image["image_id"] for image in item["images"]}
                for image in item["images"]:
                    previous = self._db.execute("SELECT * FROM catalog_images WHERE image_id=?", (image["image_id"],)).fetchone()
                    if previous and previous["product_id"] != product_id:
                        fail(f"records[{index}].images", "image ID belongs to a different product", "catalog_conflict")
                    serialized = canonical(image)
                    if previous is None:
                        self._db.execute("INSERT INTO catalog_images VALUES (?,?,1,?,1)",
                                         (image["image_id"], product_id, serialized))
                        changed = True
                    elif previous["source_json"] != serialized or not previous["active"]:
                        self._db.execute("UPDATE catalog_images SET version=version+1,source_json=?,active=1 WHERE image_id=?",
                                         (serialized, image["image_id"]))
                        changed = True
                for previous in self._db.execute("SELECT image_id FROM catalog_images WHERE product_id=? AND active=1", (product_id,)).fetchall():
                    if previous[0] not in current_ids:
                        self._db.execute("UPDATE catalog_images SET active=0,version=version+1 WHERE image_id=?", (previous[0],))
                        changed = True
            if changed:
                self._bump()
            # Unbuilt/stale maps are absent from import receipts, never version 0.
            ready = []
            for item in prepared:
                row = self._product(item["product_id"])
                if row["map_json"] is not None and json.loads(row["map_json"])["raw_version"] == row["raw_version"]:
                    ready.append(item["product_id"])
            return self._versions(ready, sorted(images))

    def _bump(self) -> None:
        self._db.execute("UPDATE catalog_meta SET catalog_version=catalog_version+1 WHERE singleton=1")

    def get_record(self, product_id: str) -> CatalogRecord:
        return json.loads(self._product(product_id)["record_json"])

    def raw_version(self, product_id: str) -> int:
        return self._product(product_id)["raw_version"]

    def export_records(self) -> list[CatalogRecord]:
        return [json.loads(row[0]) for row in self._db.execute("SELECT record_json FROM catalog_products ORDER BY product_id")]

    def get_product_map(self, product_id: str) -> ProductMap:
        row = self._product(product_id)
        if row["map_json"] is None:
            fail("product_map", "product map has not been built", "context_blocked")
        result = json.loads(row["map_json"])
        if result["raw_version"] != row["raw_version"]:
            fail("product_map", "raw record changed; rebuild the map", "stale_context")
        return result

    def save_product_map(self, product_map: ProductMap, *, expected_raw_version: int,
                         expected_map_version: int | None) -> ProductMap:
        """Storage only; the D2 builder supplies assertions, never generated here.

        map_version must be a positive integer placeholder. Storage assigns the
        resulting version using the expected versions, including no-op saves.
        """
        fields(product_map, {"subject", "product_id", "raw_version", "map_version", "registry_version", "assertions"}, "product_map")
        if len(canonical(product_map, "product_map").encode("utf-8")) > MAX_RECORD_BYTES:
            fail("product_map", "product map exceeds 256 KiB")
        if product_map["subject"] != "product":
            fail("product_map.subject", "user/target maps cannot be stored as products")
        if product_map["registry_version"] != self.registry.version:
            fail("product_map.registry_version", "unsupported registry", "unsupported_contract")
        version(expected_raw_version, "expected_raw_version")
        if expected_map_version is not None:
            version(expected_map_version, "expected_map_version")
        for name in ("raw_version", "map_version"):
            version(product_map[name], f"product_map.{name}")
        with self._transaction(write=True):
            row = self._product(product_map["product_id"])
            if (expected_raw_version != row["raw_version"] or product_map["raw_version"] != row["raw_version"]
                    or expected_map_version != row["map_version"]):
                fail("product_map", "expected raw/map version does not match", "version_conflict")
            record = json.loads(row["record_json"])
            validate_assertions(product_map["assertions"], record, self.registry, "product_map.assertions")
            incoming = json.loads(canonical(product_map))
            incoming["map_version"] = row["map_version"] or 1
            if row["map_json"] is not None and canonical(incoming) == row["map_json"]:
                return incoming
            incoming["map_version"] = (row["map_version"] or 0) + 1
            self._db.execute("UPDATE catalog_products SET map_version=?,map_json=? WHERE product_id=?",
                             (incoming["map_version"], canonical(incoming), product_map["product_id"]))
            self._bump()
            return incoming

    def _versions(self, product_ids: list[str], image_ids: list[str]) -> CatalogVersions:
        products = []
        for product_id in product_ids:
            product_map = self.get_product_map(product_id)
            products.append({"product_id": product_id, "raw_version": product_map["raw_version"],
                             "map_version": product_map["map_version"]})
        images = [{"image_id": image_id, "version": self._image(image_id)["version"]} for image_id in image_ids]
        return {"catalog_version": self._db.execute("SELECT catalog_version FROM catalog_meta WHERE singleton=1").fetchone()[0],
                "products": products, "images": images}

    def current_versions(self, product_ids: list[str], image_ids: list[str]) -> CatalogVersions:
        for name, ids in (("product_ids", product_ids), ("image_ids", image_ids)):
            if not isinstance(ids, list) or len(ids) > 256:
                fail(name, "at most 256 IDs required")
            for item in ids:
                identifier(item, name)
            if len(set(ids)) != len(ids):
                fail(name, "duplicate IDs")
        with self._transaction():
            return self._versions(product_ids, image_ids)

    def resolve_image(self, image_id: str, *, version: int) -> ImageSource:
        from .catalog_validation import version as validate_version

        validate_version(version, "image.version")
        row = self._image(image_id)
        if row["version"] != version:
            fail("image.version", "image version changed", "version_conflict")
        source = json.loads(row["source_json"])
        if source["kind"] == "remote":
            if urlsplit(source["location"]).hostname.lower() not in self.allowed_image_hosts:
                fail("image", "remote image display is not permitted for this supplier", "not_found")
        else:
            self._local_bytes(source)
        return source

    def read_image(self, image_id: str, *, version: int) -> tuple[bytes, str]:
        """For A's ID/version HTTP route; no caller-supplied path or URL fetch."""
        from .catalog_validation import version as validate_version

        validate_version(version, "image.version")
        row = self._image(image_id)
        if row["version"] != version:
            fail("image.version", "image version changed", "version_conflict")
        source = json.loads(row["source_json"])
        if source["kind"] != "local":
            fail("image", "remote references are never fetched by the server", "not_found")
        return self._local_bytes(source)

    def _local_bytes(self, source: ImageSource) -> tuple[bytes, str]:
        if self.image_root is None:
            fail("image", "local image is unavailable without a configured root", "not_found")
        self._check_local_root(source, "image.location")
        # Walk with dir_fd/O_NOFOLLOW so symlink replacement cannot redirect a
        # validated reference into an arbitrary local file. FIFOs/devices fail.
        descriptor = None
        try:
            descriptor = os.open(self.image_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            parts = source["location"].split("/")
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            with os.fdopen(leaf, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMAGE_BYTES:
                    fail("image", "image must be a bounded regular raster file")
                data = stream.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            fail("image", "local image file is missing or inaccessible", "not_found")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if len(data) > MAX_IMAGE_BYTES:
            fail("image", "image exceeds the display size limit")
        mime = IMAGE_TYPES[Path(source["location"]).suffix.lower()]
        valid = {
            "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
            "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        }[mime]
        if not valid:
            fail("image", "file signature does not match a permitted raster type")
        if source["sha256"] is not None and hashlib.sha256(data).hexdigest() != source["sha256"].lower():
            fail("image.sha256", "local image differs from its supplied hash", "stale_context")
        return data, mime
