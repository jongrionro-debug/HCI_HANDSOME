"""ADR 0013 graph engine over real HTTP/SQLite with a scripted model and synthetic images."""
import json
import sys
import threading

from stylemate_memory.consumer import make_server
from tests.consumer_browser_fixture import synthetic_image
from tests.test_graph_engine import FITS, GraphEngineTests

COLORS = {"Wide": (40, 70, 110), "Straight": (110, 80, 50), "Skinny": (60, 60, 60), "Slim": (120, 120, 90)}


def main():
    case = GraphEngineTests("test_turn_loop_grid_feedback_adjust_final_and_checkpoint")
    case.setUp()
    for path in sorted((case.root / "images").glob("*.png")):
        index = int(path.stem[1:])
        path.write_bytes(synthetic_image(COLORS[FITS[index]], FITS[index]))
    case.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
               "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": "출근할 때 입을 편한 바지"})
    server = make_server(case.service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}"}), flush=True)
    try:
        for line in sys.stdin:
            command = json.loads(line)
            if command["op"] == "close":
                break
            case.service.wait_idle()
            state = case.service.state()
            intent = case.service._graph.intent(state["request"]["id"])
            print(json.dumps({"state": state, "intent": intent,
                              "snapshot": case.service.inspect_request(state["request"]["id"])["snapshot"]}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        case.doCleanups()


if __name__ == "__main__":
    main()
