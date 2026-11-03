"""E2 browser harness: production HTTP/service, temporary SQLite, fake model.

Controls travel over the parent process's stdin, never through product HTTP.
No credentials, external traffic, or persisted browser-test data are needed.
"""

from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import zlib

from stylemate_memory.app import ConsumerService
from stylemate_memory.consumer import make_server
from stylemate_memory.llm import OpenAIResponsesGateway
from tests.test_consumer_service import FakeTransport, product


class BrowserTransport(FakeTransport):
    def __call__(self, url, headers, payload, timeout):
        response = super().__call__(url, headers, payload, timeout)
        inputs = json.loads(payload["input"])
        inputs = inputs.get("payload", inputs)
        if "candidates" in payload["text"]["format"]["schema"]["properties"]:
            value = json.loads(response["output"][0]["content"][0]["text"])
            if any(s["kind"] == "image_selection" for s in inputs["sources"]):
                value["questions"] = ["선택한 후보에서 어떤 점을 참고할까요?"]
            # Explicit synthetic case: preserve wording without inventing a map.
            if any(s["content"] == "미정으로 둘게요" for s in inputs["sources"]):
                for candidate in value["candidates"]:
                    candidate["bindings"] = []
            response["output"][0]["content"][0]["text"] = json.dumps(value)
        return response


def synthetic_image(rgb, fit="Wide"):
    """Small, reproducible raster; no image download or provider invocation."""
    width, height = 120, 160
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            left, right = (30, 90) if fit == "Wide" else (40, 80)
            pants = 18 <= y < 145 and left <= x < right and (y < 65 or x < 55 or x >= 65)
            row.extend(rgb if pants else (241, 240, 235))
        rows.append(b"\0" + row)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def main():
    with tempfile.TemporaryDirectory(prefix="lumi-e2-browser-") as temp:
        root = Path(temp)
        images = root / "images"
        images.mkdir()
        records = [product("navy", "Navy"), product("beige", "Beige")]
        for record, title, rgb in zip(records, ("A · 합성 네이비 바지", "B · 합성 베이지 바지"),
                                      ((35, 48, 75), (188, 169, 139))):
            record["title"] = title
            (images / record["images"][0]["location"]).write_bytes(synthetic_image(rgb))
        data = root / "synthetic.json"
        data.write_text(json.dumps(records), encoding="utf-8")
        transport = BrowserTransport()
        gateway = OpenAIResponsesGateway(model="dummy-e2-model", api_key="dummy-e2-key", transport=transport)
        def open_service():
            return ConsumerService(root / "memory.sqlite3", root / "catalog.sqlite3", gateway,
                                   user_id="synthetic-e2-user", image_root=images)
        service = open_service()
        service.import_catalog(data)
        def map_products():
            service.build_catalog_maps()
            # Preserve the legacy full-map input regression independently of
            # the new consumer's PI-only catalog-generation policy.
            def legacy_maps():
                from stylemate_memory.catalog_mapping import build_product_map
                for record in service._catalog.export_records():
                    pid = record["product_id"]
                    mapped = build_product_map(record, raw_version=service._catalog.raw_version(pid), registry=service.registry)
                    service._catalog.save_product_map(mapped, expected_raw_version=mapped["raw_version"],
                        expected_map_version=service._catalog.get_product_map(pid)["map_version"])
            service._run(legacy_maps)
            if "--sparse-maps" in sys.argv:
                # An explicitly selected small synthetic ProductMap fixture.
                # The default tests D2's entire 37-assertion output, including
                # unknown attributes, through the production model boundary.
                def supply_sparse_maps():
                    for record in records:
                        product_map = service._catalog.get_product_map(record["product_id"])
                        product_map["assertions"] = [a for a in product_map["assertions"] if a["status"] != "unknown"]
                        service._catalog.save_product_map(product_map, expected_raw_version=product_map["raw_version"],
                                                          expected_map_version=product_map["map_version"])
                service._run(supply_sparse_maps)
        map_products()
        server = thread = None
        def start(port=0):
            nonlocal server, thread
            server = make_server(service, port)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join(3)
        def emit(value):
            print(json.dumps(value, ensure_ascii=False), flush=True)
        start()
        emit({"url": f"http://127.0.0.1:{server.server_port}"})
        try:
            for line in sys.stdin:
                command = json.loads(line)
                op = command["op"]
                if op == "close":
                    emit({"closed": True})
                    break
                if op == "inspect":
                    state = service.state(command.get("request_id"))
                    result = {"state": state, "snapshot": service.inspect_request(state["request"]["id"])["snapshot"]
                              if state["request"] else None}
                elif op == "restart":
                    port = server.server_port
                    stop()
                    service.close()
                    service = open_service()
                    start(port)
                    result = {"restarted": True}
                elif op == "provider":
                    transport.fail_extract = command.get("fail_extract", False)
                    transport.fail_propose = command.get("fail_propose", False)
                    transport.pause = command.get("pause")
                    transport.entered.clear()
                    transport.release.clear()
                    result = {"configured": True}
                elif op == "release":
                    transport.release.set()
                    result = {"released": True}
                elif op == "entered":
                    result = {"entered": transport.entered.is_set()}
                elif op == "catalog":
                    supplied = deepcopy(records)
                    if command.get("empty"):
                        # Re-map the supplied records as another garment type.
                        for record in supplied:
                            record["garment_type"] = "Shirts"
                    elif command.get("change"):
                        supplied[0]["raw_metadata"]["supplier_color"] = "Black"
                    data.write_text(json.dumps(supplied), encoding="utf-8")
                    service.import_catalog(data)
                    map_products()
                    result = {"updated": True}
                else:
                    raise ValueError("unknown browser harness control")
                emit(result)
        finally:
            transport.release.set()
            stop()
            service.close()


if __name__ == "__main__":
    main()
