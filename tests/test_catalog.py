import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from stylemate_memory.catalog import Catalog, MAX_IMAGE_BYTES
from stylemate_memory.catalog_io import export_file, import_file, load_records
from stylemate_memory.contracts import V1_REGISTRY_VERSION
from stylemate_memory.errors import StyleMateError


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
# A synthetic 1x1 PNG used only inside each test's temporary image root.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aPioAAAAASUVORK5CYII=")


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lumi-catalog-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.db_path = self.root / "catalog.sqlite3"
        self.catalog = Catalog(self.db_path, image_root=self.images)
        self.addCleanup(self.catalog.close)
        self.records = load_records(FIXTURES / "valid.json")
        self.record = self.records[0]
        self.pid = self.record["product_id"]
        self.iid = self.record["images"][0]["image_id"]

    def assert_error(self, code, operation, *args, location=None, **kwargs):
        with self.assertRaises(StyleMateError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        if location is not None:
            self.assertIn(location, caught.exception.message)
        return caught.exception

    def map_for(self, record=None):
        record = self.record if record is None else record
        return {"subject": "product", "product_id": record["product_id"],
                "raw_version": self.catalog.raw_version(record["product_id"]), "map_version": 1,
                "registry_version": V1_REGISTRY_VERSION, "assertions": deepcopy(record["labels"])}

    def save_map(self, record=None, expected_map_version=None):
        value = self.map_for(record)
        return self.catalog.save_product_map(value, expected_raw_version=value["raw_version"],
                                             expected_map_version=expected_map_version)

    def test_import_reimport_export_and_restart_preserve_records_and_versions(self):
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")) as network:
            first = import_file(self.catalog, FIXTURES / "valid.json")
            self.assertEqual(first["catalog_version"], 1)
            self.assertEqual(first["products"], [])  # No generated Map is claimed.
            self.assertEqual(len(first["images"]), 2)
            self.assertEqual(import_file(self.catalog, FIXTURES / "valid.json"), first)
            self.assertEqual(self.catalog.get_record(self.pid), self.record)
            self.assertEqual(self.catalog.raw_version(self.pid), 1)
            for suffix in ("json", "jsonl"):
                path = self.root / f"export.{suffix}"
                export_file(self.catalog, path)
                self.assertEqual(load_records(path), self.records)
                self.assertEqual(import_file(self.catalog, path), first)
            import_file(self.catalog, FIXTURES / "valid.jsonl")
            self.assertEqual(len(self.catalog.export_records()), 3)
            self.assertEqual(self.catalog.get_record("synthetic-pants-3")["images"], [])
            network.assert_not_called()
        with Catalog(self.db_path, image_root=self.images) as reopened:
            self.assertEqual(reopened.export_records(), self.catalog.export_records())
            self.assertEqual(reopened.current_versions([], [self.iid]), self.catalog.current_versions([], [self.iid]))

    def test_results_are_detached_and_partial_import_does_not_delete_missing_products(self):
        self.catalog.import_records(self.records)
        result = self.catalog.get_record(self.pid)
        result["raw_metadata"]["supplier_color"] = "Black"
        self.assertEqual(self.catalog.get_record(self.pid), self.record)
        self.catalog.import_records([self.record])
        self.assertEqual(len(self.catalog.export_records()), 2)

    def test_source_identity_collision_rolls_back_entire_import(self):
        self.catalog.import_records(self.records)
        before = self.catalog.current_versions([], [self.iid])
        changed = deepcopy(self.record)
        changed["title"] = "변경됐지만 batch 실패 시 저장되면 안 됨"
        collision = deepcopy(self.records[1])
        collision["source"]["source_id"] = "different-supplier"
        self.assert_error("catalog_conflict", self.catalog.import_records, [changed, collision], location="records[1].source")
        self.assertEqual(self.catalog.export_records(), self.records)
        self.assertEqual(self.catalog.current_versions([], [self.iid]), before)
        collision = deepcopy(self.record)
        collision["source"]["url"] = "https://example.invalid/another-identity"
        self.assert_error("catalog_conflict", self.catalog.import_records, [collision])

    def test_duplicate_product_and_cross_product_image_identifiers_are_rejected(self):
        self.assert_error("catalog_conflict", self.catalog.import_records, [self.record, self.record], location="records[1].product_id")
        duplicate = deepcopy(self.records[1])
        duplicate["images"] = deepcopy(self.record["images"])
        self.assert_error("catalog_conflict", self.catalog.import_records, [self.record, duplicate], location="records[1].images[0]")
        self.assertEqual(self.catalog.export_records(), [])
        self.catalog.import_records([self.record])
        before = self.catalog.current_versions([], [])
        self.assert_error("catalog_conflict", self.catalog.import_records, [duplicate])
        self.assert_error("not_found", self.catalog.get_record, duplicate["product_id"])
        self.assertEqual(self.catalog.current_versions([], []), before)

    def test_missing_or_stale_map_is_not_reported_as_a_fresh_dependency(self):
        self.catalog.import_records([self.record])
        self.assert_error("context_blocked", self.catalog.get_product_map, self.pid)
        self.assert_error("context_blocked", self.catalog.current_versions, [self.pid], [])
        self.save_map()
        updated = deepcopy(self.record)
        updated["source"]["collected_at"] = "2026-10-30T12:00:00+09:00"
        receipt = self.catalog.import_records([updated])
        self.assertEqual(receipt["products"], [])
        self.assertEqual(self.catalog.raw_version(self.pid), 2)
        self.assert_error("stale_context", self.catalog.get_product_map, self.pid)
        self.assert_error("stale_context", self.catalog.current_versions, [self.pid], [])
        saved = self.save_map(updated, expected_map_version=1)
        self.assertEqual((saved["raw_version"], saved["map_version"]), (2, 2))

    def test_map_and_image_versions_change_independently_and_survive_restart(self):
        self.catalog.import_records([self.record])
        original_map = self.save_map()
        before = self.catalog.current_versions([self.pid], [self.iid])
        changed = deepcopy(self.record)
        changed["images"][0]["source_revision"] = "supplied-2"
        self.catalog.import_records([changed])
        after = self.catalog.current_versions([self.pid], [self.iid])
        self.assertEqual(after["products"], before["products"])
        self.assertEqual(after["images"][0]["version"], 2)
        self.assertGreater(after["catalog_version"], before["catalog_version"])
        self.assertEqual(self.catalog.get_product_map(self.pid), original_map)
        self.assert_error("version_conflict", self.catalog.resolve_image, self.iid, version=1)
        new_map = self.map_for()
        new_map["assertions"] = []  # No facts are fabricated by storage.
        saved = self.catalog.save_product_map(new_map, expected_raw_version=1, expected_map_version=1)
        self.assertEqual(saved["map_version"], 2)
        latest = self.catalog.current_versions([self.pid], [self.iid])
        self.assertEqual(latest["images"], after["images"])
        self.assertEqual(latest["products"][0]["map_version"], 2)
        self.assertEqual(self.catalog.save_product_map(new_map, expected_raw_version=1, expected_map_version=2), saved)
        self.assertEqual(self.catalog.current_versions([self.pid], [self.iid]), latest)
        with Catalog(self.db_path) as reopened:
            self.assertEqual(reopened.current_versions([self.pid], [self.iid]), latest)
            self.assertEqual(reopened.get_product_map(self.pid), saved)

    def test_each_supplied_image_axis_invalidates_old_versions_without_raw_changes(self):
        self.catalog.import_records([self.record])
        for revision, (key, value) in enumerate((
                ("location", "replacement.png"), ("sha256", "a" * 64),
                ("regions", []), ("source_revision", "next-supply")), 2):
            updated = self.catalog.get_record(self.pid)
            updated["images"][0][key] = value
            self.catalog.import_records([updated])
            self.assertEqual(self.catalog.raw_version(self.pid), 1)
            self.assertEqual(self.catalog.current_versions([], [self.iid])["images"][0]["version"], revision)

    def test_removed_and_reintroduced_image_does_not_reuse_an_old_version(self):
        self.catalog.import_records([self.record])
        without = deepcopy(self.record)
        without["images"] = []
        self.catalog.import_records([without])
        self.assert_error("not_found", self.catalog.current_versions, [], [self.iid])
        self.catalog.import_records([self.record])
        self.assertEqual(self.catalog.current_versions([], [self.iid])["images"][0]["version"], 3)
        self.assert_error("version_conflict", self.catalog.resolve_image, self.iid, version=1)

    def test_closed_fields_source_values_and_registry_errors_have_record_locations(self):
        cases = [
            ("source", None, "invalid_input"),
            ("format_version", "lumi-catalog-v99", "unsupported_contract"),
            ("title", "", "invalid_input"),
            ("description", "", "invalid_input"),
            ("product_id", "x" * 129, "invalid_input"),
            ("raw_metadata", {"not_finite": float("nan")}, "invalid_input"),
            ("raw_metadata", {1: "not a string key"}, "invalid_input"),
            ("raw_metadata", {"too_large": "x" * (256 * 1024)}, "invalid_input"),
            ("raw_version", 99, "invalid_input"),
        ]
        for field, value, code in cases:
            with self.subTest(field=field, code=code):
                bad = deepcopy(self.record)
                bad[field] = value
                self.assert_error(code, self.catalog.import_records, [self.records[1], bad], location="records[1]")
        for field in ("source_id", "url", "collected_at"):
            bad = deepcopy(self.record)
            del bad["source"][field]
            self.assert_error("invalid_input", self.catalog.import_records, [bad], location="records[0].source")
        for value in ("not-a-url", "file:///private/anything", "https://name:password@example.invalid/a"):
            bad = deepcopy(self.record)
            bad["source"]["url"] = value
            self.assert_error("invalid_input", self.catalog.import_records, [bad], location="source.url")
        bad = deepcopy(self.record)
        bad["labels"][0]["observation"]["values"] = ["Invented color"]
        self.assert_error("unsupported_mapping", self.catalog.import_records, [bad], location="labels[0].observation")
        self.assertEqual(self.catalog.export_records(), [])

    def test_unknown_unverified_and_model_provenance_never_become_confirmed(self):
        bad = deepcopy(self.record)
        bad["labels"][1]["status"] = "confirmed"  # Review feeling is not verified performance.
        self.assert_error("invalid_input", self.catalog.import_records, [bad], location="labels[1]")
        for field in ("verifier", "verified_at", "evidence_ref"):
            bad = deepcopy(self.record)
            bad["labels"][0]["provenance"][0][field] = None
            self.assert_error("invalid_input", self.catalog.import_records, [bad], location="provenance[0]")
        bad = deepcopy(self.record)
        bad["labels"][0]["provenance"][0]["quote"] = "fabricated quote"
        self.assert_error("invalid_input", self.catalog.import_records, [bad], location="quote")
        bad = deepcopy(self.record)
        bad["labels"][2]["observation"]["values"] = ["Cotton"]
        self.assert_error("invalid_input", self.catalog.import_records, [bad], location="labels[2]")
        inferred = deepcopy(self.record)
        label = inferred["labels"][0]
        label["status"] = "inferred"
        label["provenance"][0].update(kind="model_interpretation", verifier=None, verified_at=None, evidence_ref=None)
        self.catalog.import_records([inferred])
        self.assertEqual(self.catalog.get_record(self.pid)["labels"][0]["status"], "inferred")
        label["status"] = "confirmed"
        self.assert_error("invalid_input", self.catalog.import_records, [inferred])

    def test_unsupported_garment_raw_data_is_preserved_without_invented_mappings(self):
        other = deepcopy(self.record)
        other.update(garment_type="Dress", labels=[])
        self.catalog.import_records([other])
        self.assertEqual(self.catalog.get_record(self.pid)["garment_type"], "Dress")
        other["labels"] = deepcopy(self.record["labels"])
        self.assert_error("unsupported_mapping", self.catalog.import_records, [other])

    def test_confirmed_pi_can_use_exact_canonical_metadata_but_prose_and_performance_cannot(self):
        direct = deepcopy(self.record)
        provenance = direct["labels"][0]["provenance"][0]
        provenance.update(kind="raw_metadata", verifier=None, evidence_ref=None, verified_at=None)
        self.catalog.import_records([direct])
        self.assertEqual(self.catalog.get_record(self.pid)["labels"][0]["status"], "confirmed")
        direct["raw_metadata"]["supplier_color"] = "Navy가 아닌 색"
        self.assert_error("invalid_input", self.catalog.import_records, [direct])
        unverified = deepcopy(self.record)
        warmth = unverified["labels"][1]
        warmth["status"] = "confirmed"
        warmth["provenance"][0].update(kind="raw_metadata", verifier=None)
        self.assert_error("invalid_input", self.catalog.import_records, [unverified])

    def test_map_storage_checks_expected_versions_and_rejects_target_or_invalid_maps(self):
        self.catalog.import_records([self.record])
        payload = self.map_for()
        for raw, mapped in ((True, None), (0, None), (1, False), (1, 0)):
            self.assert_error("invalid_input", self.catalog.save_product_map, payload,
                              expected_raw_version=raw, expected_map_version=mapped)
        self.assert_error("version_conflict", self.catalog.save_product_map, payload,
                          expected_raw_version=2, expected_map_version=None)
        for key, value, code in (("map_version", True, "invalid_input"), ("raw_version", 0, "invalid_input"),
                                 ("subject", "user", "invalid_input"), ("registry_version", "consumer-17-v1", "unsupported_contract")):
            bad = deepcopy(payload)
            bad[key] = value
            self.assert_error(code, self.catalog.save_product_map, bad, expected_raw_version=1, expected_map_version=None)
        self.save_map()
        self.assert_error("version_conflict", self.catalog.save_product_map, payload,
                          expected_raw_version=1, expected_map_version=None)
        self.assert_error("version_conflict", self.catalog.save_product_map, payload,
                          expected_raw_version=1, expected_map_version=2)

    def test_missing_images_are_explicitly_unavailable_without_placeholder_files(self):
        self.catalog.import_records([self.record])
        self.assert_error("not_found", self.catalog.resolve_image, self.iid, version=1, location="missing or inaccessible")
        self.assertEqual(list(self.images.iterdir()), [])
        with Catalog(self.db_path) as no_root:
            self.assert_error("not_found", no_root.resolve_image, self.iid, version=1, location="without a configured root")
        for value in (True, 0, -1, "1"):
            self.assert_error("invalid_input", self.catalog.resolve_image, self.iid, version=value)

    def test_local_raster_display_is_id_version_scoped_and_hash_checked(self):
        image = deepcopy(self.record)
        image["images"][0]["sha256"] = hashlib.sha256(PNG).hexdigest()
        (self.images / "pants-1.png").write_bytes(PNG)
        self.catalog.import_records([image])
        self.assertEqual(self.catalog.resolve_image(self.iid, version=1), image["images"][0])
        self.assertEqual(self.catalog.read_image(self.iid, version=1), (PNG, "image/png"))
        (self.images / "pants-1.png").write_bytes(PNG + b"changed bytes")
        self.assert_error("stale_context", self.catalog.resolve_image, self.iid, version=1, location="sha256")
        self.assert_error("not_found", self.catalog.read_image, "missing", version=1)

    def test_traversal_svg_schemes_and_symlink_escape_are_rejected(self):
        for location in ("../outside.png", "/etc/anything.png", "folder/../../outside.png", "folder\\outside.png",
                         "%2e%2e/outside.png", "file:outside.png", "./pants.png", "x//pants.png", "vector.svg"):
            bad = deepcopy(self.record)
            bad["images"][0]["location"] = location
            self.assert_error("invalid_input", self.catalog.import_records, [bad], location="images[0].location")
        outside = self.root / "outside.png"
        outside.write_bytes(PNG)
        (self.images / "pants-1.png").symlink_to(outside)
        self.assert_error("invalid_input", self.catalog.import_records, [self.record], location="images[0].location")
        (self.images / "pants-1.png").unlink()
        self.catalog.import_records([self.record])
        (self.images / "pants-1.png").symlink_to(outside)
        self.assert_error("invalid_input", self.catalog.read_image, self.iid, version=1)

    def test_non_raster_large_and_special_files_are_not_displayed(self):
        self.catalog.import_records([self.record])
        leaf = self.images / "pants-1.png"
        leaf.write_text("<html>this is not a PNG</html>")
        self.assert_error("invalid_input", self.catalog.read_image, self.iid, version=1, location="signature")
        with leaf.open("wb") as stream:
            stream.truncate(MAX_IMAGE_BYTES + 1)
        self.assert_error("invalid_input", self.catalog.read_image, self.iid, version=1, location="bounded regular")
        leaf.unlink()
        os.mkfifo(leaf)
        self.assert_error("invalid_input", self.catalog.read_image, self.iid, version=1)

    def test_remote_display_requires_explicit_supplier_allowlist_and_never_fetches(self):
        self.catalog.import_records(self.records)
        image = self.records[1]["images"][0]
        self.assert_error("not_found", self.catalog.resolve_image, image["image_id"], version=1)
        with Catalog(self.db_path, allowed_image_hosts=("images.example.invalid",)) as allowed:
            with patch("socket.create_connection", side_effect=AssertionError("no fetch")) as network:
                self.assertEqual(allowed.resolve_image(image["image_id"], version=1), image)
                self.assert_error("not_found", allowed.read_image, image["image_id"], version=1)
                network.assert_not_called()
        for location in ("http://images.example.invalid/x.png", "file:///tmp/x.png",
                         "https://name:password@images.example.invalid/x.png", "https://images.example.invalid:8443/x.png"):
            bad = deepcopy(self.records[1])
            bad["images"][0]["location"] = location
            self.assert_error("invalid_input", self.catalog.import_records, [bad])

    def test_regions_hashes_and_freshness_arguments_are_validated(self):
        for box in ([0, 0, 0, 1], [-0.1, 0, 1, 1], [0, 0, 2, 1], [True, 0, 1, 1], [0, 0, 1]):
            bad = deepcopy(self.record)
            bad["images"][0]["regions"][0]["box"] = box
            self.assert_error("invalid_input", self.catalog.import_records, [bad], location=".box")
        bad = deepcopy(self.record)
        bad["images"][0]["sha256"] = "not-a-hash"
        self.assert_error("invalid_input", self.catalog.import_records, [bad], location="sha256")
        bad = deepcopy(self.record)
        bad["images"][0]["regions"] *= 2
        self.assert_error("invalid_input", self.catalog.import_records, [bad], location="regions[1]")
        for products, images in (([True], []), ([], [None]), ([], [self.iid, self.iid]), ("not-list", [])):
            self.assert_error("invalid_input", self.catalog.current_versions, products, images)

    def test_file_errors_duplicate_json_keys_and_invalid_fixture_report_locations(self):
        self.assert_error("invalid_input", import_file, self.catalog, FIXTURES / "invalid.jsonl", location="JSONL line 1.source.collected_at")
        for path in (self.root / "missing.json", self.root / "input.csv", self.root / "directory.json"):
            if path.name == "directory.json":
                path.mkdir()
            self.assert_error("invalid_input", import_file, self.catalog, path)
        cases = (("bad.json", '{"not": "an array"}'), ("bad.jsonl", '\n\n{"format_version":"x"'),
                 ("bad.json", '[{"product_id":"a","product_id":"b"}]'), ("bad.json", '[NaN]'))
        for filename, content in cases:
            path = self.root / filename
            path.write_text(content, encoding="utf-8")
            self.assert_error("invalid_input", import_file, self.catalog, path)
        path = self.root / "invalid-encoding.json"
        path.write_bytes(b"\xff")
        self.assert_error("invalid_input", import_file, self.catalog, path)
        path = self.root / "located.jsonl"
        bad = deepcopy(self.record)
        bad["source"]["collected_at"] = "2026-10-29"
        path.write_text("\n" + json.dumps(self.records[1]) + "\n\n" + json.dumps(bad) + "\n")
        self.assert_error("invalid_input", import_file, self.catalog, path, location="JSONL line 4.source.collected_at")
        self.assertEqual(self.catalog.export_records(), [])

    def test_export_write_failure_preserves_existing_output_and_cleans_temporary_files(self):
        self.catalog.import_records([self.record])
        target = self.root / "preserved.json"
        target.write_text("original", encoding="utf-8")
        with patch("stylemate_memory.catalog_io.os.replace", side_effect=OSError("simulated write failure")):
            self.assert_error("invalid_input", export_file, self.catalog, target)
        self.assertEqual(target.read_text(), "original")
        self.assertEqual(list(self.root.glob(".lumi-catalog-*")), [])

    def test_catalog_refuses_user_database_or_unsupported_catalog_format(self):
        user_db = self.root / "user-memory.sqlite3"
        with closing(sqlite3.connect(user_db)) as connection:
            connection.execute("CREATE TABLE memories (content TEXT)")
            connection.commit()
        self.assert_error("unsupported_contract", Catalog, user_db)
        with closing(sqlite3.connect(user_db)) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("memories",)])
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE catalog_meta SET format_version='unsupported'")
            connection.commit()
        self.assert_error("unsupported_contract", Catalog, self.db_path)

    def test_unicode_line_separators_round_trip_and_invalid_utf8_is_rejected(self):
        record = deepcopy(self.record)
        record["title"] = "합성\u2028바지"
        self.catalog.import_records([record])
        path = self.root / "unicode.jsonl"
        export_file(self.catalog, path)
        self.assertEqual(import_file(self.catalog, path), self.catalog.current_versions([], [self.iid]))
        record["title"] = "\ud800"
        self.assert_error("invalid_input", self.catalog.import_records, [record])

    def test_invalid_configuration_and_export_over_database_are_rejected(self):
        for kwargs in ({"db_path": None}, {"db_path": ""}, {"db_path": self.db_path, "image_root": True},
                       {"db_path": self.db_path, "allowed_image_hosts": (True,)},
                       {"db_path": self.db_path, "allowed_image_hosts": ("127.0.0.1",)}):
            self.assert_error("invalid_input", Catalog, **kwargs)
        # Suffix alone must not let an export replace a database supplied by the user.
        path = self.root / "catalog-as-json.json"
        with Catalog(path) as catalog:
            catalog.import_records([self.record])
            self.assert_error("invalid_input", export_file, catalog, path)
            self.assertEqual(catalog.get_record(self.pid), self.record)


if __name__ == "__main__":
    unittest.main()
