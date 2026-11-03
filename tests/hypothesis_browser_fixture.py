"""Synthetic PI-only catalog and deterministic FEA->PI model; real HTTP/SQLite."""
import json
import threading

from stylemate_memory.consumer import make_server
from tests.consumer_browser_fixture import synthetic_image
from tests.test_hypotheses import HypothesisTests


def main():
    case = HypothesisTests("test_restart_preserves_issued_comparison")
    case.setUp()
    for record in case.records:
        (case.images / record["images"][0]["location"]).write_bytes(
            synthetic_image((35, 48, 75), record["raw_metadata"]["supplier_fit"]))
    case.comparison()
    server = make_server(case.service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}"}), flush=True)
    try:
        for line in __import__("sys").stdin:
            command = json.loads(line)
            if command["op"] == "close":
                break
            if command["op"] == "reset":
                case.comparison()
            if command["op"] == "change_catalog":
                case.records[0]["images"][0]["source_revision"] += "-changed"
                case.data.write_text(json.dumps(case.records))
                case.service.import_catalog(case.data)
            case.service.wait_idle()
            print(json.dumps({"state": case.state(), "snapshot": case.snapshot()}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        case.doCleanups()


if __name__ == "__main__":
    main()
