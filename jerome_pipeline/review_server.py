from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import PipelineConfig
from .editorial import EditorialRevisionConflict, EditorialRevisionError
from .review import ReviewRepository


STATIC_ROOT = Path(__file__).with_name("reviewer_ui")


class ReviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        repository: ReviewRepository,
    ):
        self.repository = repository
        super().__init__(server_address, ReviewRequestHandler)


class ReviewRequestHandler(BaseHTTPRequestHandler):
    server: ReviewHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, relative: str) -> None:
        requested = (STATIC_ROOT / relative).resolve()
        root = STATIC_ROOT.resolve()
        if requested != root and root not in requested.parents:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if requested.is_dir():
            requested = requested / "index.html"
        if not requested.exists() or not requested.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        body = requested.read_bytes()
        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        route = urlparse(self.path).path
        if route == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "mode": "immutable_machine_append_only_editorial",
                    "book": self.server.repository.book,
                },
            )
            return
        if route == "/api/chunks":
            self._send_json(HTTPStatus.OK, self.server.repository.list_chunks())
            return
        if route.startswith("/api/chunks/"):
            chunk_id = unquote(route[len("/api/chunks/") :])
            value = self.server.repository.get_chunk(chunk_id)
            if value is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "chunk_not_found", "chunk_id": chunk_id},
                )
            else:
                self._send_json(HTTPStatus.OK, value)
            return
        if route == "/":
            self._send_static("index.html")
            return
        self._send_static(unquote(route.lstrip("/")))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        route = urlparse(self.path).path
        parts = [unquote(part) for part in route.strip("/").split("/")]
        if (
            len(parts) == 5
            and parts[0:2] == ["api", "chunks"]
            and parts[3:5] == ["editorial", "revisions"]
        ):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > 2_000_000:
                self._send_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"error": "request_too_large"},
                )
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_json", "message": str(exc)},
                )
                return
            try:
                value = self.server.repository.save_editorial_revision(
                    parts[2], payload
                )
            except EditorialRevisionConflict as exc:
                self._send_json(
                    HTTPStatus.CONFLICT,
                    {"error": "revision_conflict", "message": str(exc)},
                )
                return
            except EditorialRevisionError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_editorial_revision", "message": str(exc)},
                )
                return
            if value is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "chunk_not_found", "chunk_id": parts[2]},
                )
                return
            self._send_json(HTTPStatus.CREATED, value)
            return
        self._mutation_not_allowed()

    def _mutation_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {
                "error": "machine_artifacts_immutable",
                "message": (
                    "Only append-only editorial revision creation is allowed; "
                    "pipeline artifacts are never mutated."
                ),
            },
        )

    do_PUT = _mutation_not_allowed  # type: ignore[assignment]
    do_PATCH = _mutation_not_allowed  # type: ignore[assignment]
    do_DELETE = _mutation_not_allowed  # type: ignore[assignment]


@dataclass
class RunningReviewServer:
    server: ReviewHTTPServer
    thread: threading.Thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_review_server(
    config: PipelineConfig,
    *,
    book: int = 1,
    profile: str = "production",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> RunningReviewServer:
    repository = ReviewRepository(config=config, book=book, profile=profile)
    server = ReviewHTTPServer((host, port), repository)
    thread = threading.Thread(
        target=server.serve_forever,
        name="jerome-reviewer",
        daemon=True,
    )
    thread.start()
    return RunningReviewServer(server=server, thread=thread)


def serve_review(
    config: PipelineConfig,
    *,
    book: int = 1,
    profile: str = "production",
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    repository = ReviewRepository(config=config, book=book, profile=profile)
    server = ReviewHTTPServer((host, port), repository)
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/"
    print(f"Jerome Reviewer UI (append-only editorial revisions): {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
