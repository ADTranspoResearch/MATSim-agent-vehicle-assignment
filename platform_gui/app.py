from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import core, whatif


STATIC_DIR = Path(__file__).resolve().parent / "static"


def load_index_html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


class PlatformHandler(BaseHTTPRequestHandler):
    server_version = "MATSimPlatform/0.1"

    def log_message(self, format: str, *args) -> None:
        if args and "/api/progress" in str(args[0]):
            return
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                body = load_index_html().encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/config":
                config = core.load_config()
                self.send_json({"config": config, "options": core.list_vehicle_options(config)})
            elif parsed.path == "/api/options":
                config = core.load_config()
                self.send_json({"options": core.list_vehicle_options(config)})
            elif parsed.path == "/api/vehicle-files":
                config = core.load_config()
                self.send_json({"files": core.list_assignment_vehicle_files(config)})
            elif parsed.path.startswith("/api/whatif/"):
                self.handle_whatif_get(parsed.path.removeprefix("/api/whatif/"))
            elif parsed.path.startswith("/static/"):
                self.serve_static(parsed.path.removeprefix("/static/"))
            elif parsed.path == "/api/progress":
                task_id = parse_qs(parsed.query).get("task", [""])[0]
                self.send_json(core.read_progress(task_id))
            elif parsed.path == "/file":
                self.serve_file(parsed.query)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        task_id = None
        try:
            payload = self.read_json()
            task_id = payload.get("task_id")
            progress = core.progress_reporter(task_id)
            if self.path == "/api/config":
                config = {**core.load_config(), **(payload.get("config") or {})}
                core.save_config(config)
                self.send_json({"ok": True})
            elif self.path == "/api/assign":
                config = payload.get("config") or core.load_config()
                result = core.assign_vehicle_types(
                    config=config,
                    year=int(payload["year"]),
                    source=payload["source"],
                    scenario=payload.get("scenario") or "HISTORICAL",
                    seed=int(payload.get("seed", 2)),
                    ev_factor=float(payload.get("ev_factor", 1.0)),
                    progress=progress,
                )
                core.save_config(config)
                self.send_json(
                    {
                        "output_file": core.display_path(result.output_file),
                        "distribution_file": core.display_path(result.distribution_file),
                        "assigned_count": result.assigned_count,
                        "transit_vehicle_count": result.transit_vehicle_count,
                        "type_counts": result.type_counts,
                        "projected_share": result.projected_share,
                        "fallback_fsas": result.fallback_fsas,
                    }
                )
            elif self.path == "/api/projected-share":
                config = payload.get("config") or core.load_config()
                self.send_json(
                    {
                        "projected_share": core.projected_quebec_city_share(
                            config=config,
                            year=int(payload["year"]),
                            scenario=payload.get("scenario") or "BAU",
                            ev_factor=float(payload.get("ev_factor", 1.0)),
                            source=payload.get("source") or "predicted",
                        )
                    }
                )
            elif self.path == "/api/results":
                config = payload.get("config") or core.load_config()
                metric = payload.get("metric")
                year = int(payload["year"])
                scenario = payload.get("scenario") or "BAU"
                core.save_config(config)
                if metric == "co2":
                    self.send_json(
                        core.generate_co2_results(config, year, scenario, progress=progress)
                    )
                elif metric == "ev":
                    vehicle_file = payload.get("vehicle_file")
                    if not vehicle_file:
                        raise ValueError("EV results require an assigned vehicle file.")
                    self.send_json(
                        core.generate_ev_results(
                            config, year, scenario, vehicle_file, progress=progress
                        )
                    )
                else:
                    raise ValueError(f"Unknown metric: {metric}")
            elif self.path == "/api/run-emissions":
                config = payload.get("config") or core.load_config()
                result = core.run_emission_module(
                    config=config,
                    year=int(payload["year"]),
                    scenario=payload.get("scenario") or "BAU",
                    vehicle_file=payload["vehicle_file"],
                    progress=progress,
                )
                core.save_config(config)
                self.send_json(result)
            elif self.path.startswith("/api/whatif/"):
                self.handle_whatif_post(self.path.removeprefix("/api/whatif/"), payload)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            core.clear_progress(task_id)

    def handle_whatif_get(self, name: str) -> None:
        engine = whatif.get_engine(core.load_config())
        if name == "meta":
            self.send_json(engine.describe())
        elif name == "geometry":
            self.send_json(engine.geometry())
        elif name == "scenarios":
            self.send_json(engine.scenario_tables())
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def handle_whatif_post(self, name: str, payload: dict) -> None:
        engine = whatif.get_engine(core.load_config(), force=name == "rebuild")
        if name == "run":
            self.send_json(engine.run(payload))
        elif name == "policy":
            self.send_json(engine.policy(payload))
        elif name == "stability":
            self.send_json(engine.stability(payload))
        elif name == "rebuild":
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if STATIC_DIR.resolve() not in path.parents or not path.is_file():
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, query: str) -> None:
        params = parse_qs(query)
        raw_path = params.get("path", [""])[0]
        if not raw_path:
            self.send_json({"error": "Missing path"}, HTTPStatus.BAD_REQUEST)
            return
        path = core.resolve_path(raw_path).resolve()
        root = core.PROJECT_ROOT.resolve()
        if root not in path.parents and path != root:
            self.send_json({"error": "File path is outside the project"}, HTTPStatus.FORBIDDEN)
            return
        if not path.is_file():
            self.send_json({"error": f"File not found: {raw_path}"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MATSim vehicle assignment GUI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), PlatformHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"MATSim Vehicle Assignment Platform running at {url}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
