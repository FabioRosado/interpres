from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .config import ConfigurationError, PipelineConfig, load_config
from .editorial import EditorialRevisionConflict, EditorialRevisionError
from .review import ReviewRepository

STATIC_ROOT = Path(__file__).with_name("reviewer_ui")
DIST_ROOT = STATIC_ROOT / "dist"


def _static_root() -> Path:
    return DIST_ROOT if DIST_ROOT.exists() else STATIC_ROOT


def _npm_available() -> bool:
    return shutil.which("npm") is not None


def _start_vite_dev(ui_dir: Path) -> subprocess.Popen | None:
    if not _npm_available():
        return None
    return subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=ui_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
    )


class ReviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        repository: ReviewRepository,
        catalog: "ReviewProjectCatalog",
    ):
        self.repository = repository
        self.catalog = catalog
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
        root = _static_root().resolve()
        requested = (root / relative).resolve()
        if requested != root and root not in requested.parents:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not requested.is_file() and root == DIST_ROOT.resolve():
            fallback_root = STATIC_ROOT.resolve()
            fallback = (fallback_root / relative).resolve()
            if fallback == fallback_root or fallback_root in fallback.parents:
                requested = fallback
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

    def _repository_from_query(self) -> ReviewRepository:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        project_id = (query.get("project") or [None])[0]
        raw_book = (query.get("book") or [None])[0]
        raw_profile = (query.get("profile") or [None])[0]
        book = self.server.repository.book
        if raw_book:
            try:
                book = int(raw_book)
            except ValueError:
                raise ValueError(f"Invalid book: {raw_book!r}")
        profile = raw_profile or self.server.repository.profile
        return self.server.catalog.repository(
            project_id or self.server.catalog.default_project_id,
            book=book,
            profile=profile,
        )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        route = urlparse(self.path).path
        if route == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "mode": "immutable_machine_append_only_editorial",
                    "book": self.server.repository.book,
                    "project": self.server.catalog.default_project_id,
                },
            )
            return
        if route == "/api/projects":
            self._send_json(HTTPStatus.OK, self.server.catalog.to_api())
            return
        if route == "/api/chunks":
            try:
                repository = self._repository_from_query()
            except (ConfigurationError, ValueError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_project_selection", "message": str(exc)},
                )
                return
            self._send_json(HTTPStatus.OK, repository.list_chunks())
            return
        if route.startswith("/api/chunks/"):
            try:
                repository = self._repository_from_query()
            except (ConfigurationError, ValueError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_project_selection", "message": str(exc)},
                )
                return
            # Handle /api/chunks/{id}/review-links
            if route.startswith("/api/chunks/") and route.endswith("/review-links"):
                chunk_id = unquote(route[len("/api/chunks/") : -len("/review-links")])
                view = repository.get_chunk(chunk_id)
                if view is None:
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        {"error": "chunk_not_found", "chunk_id": chunk_id},
                    )
                else:
                    self._send_json(HTTPStatus.OK, view.get("review_links", {}))
                return
            # Handle /api/chunks/{id}
            chunk_id = unquote(route[len("/api/chunks/") :])
            value = repository.get_chunk(chunk_id)
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
                repository = self._repository_from_query()
            except (ConfigurationError, ValueError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_project_selection", "message": str(exc)},
                )
                return
            try:
                value = repository.save_editorial_revision(
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


@dataclass(frozen=True)
class ReviewProject:
    project_id: str
    title: str
    path: Path
    config: PipelineConfig
    books: list[int]


class ReviewProjectCatalog:
    def __init__(self, default_config: PipelineConfig):
        self.default_project_id = default_config.project_id
        self._projects = self._discover(default_config)

    @staticmethod
    def _candidate_config_paths(default_config: PipelineConfig) -> list[Path]:
        paths: list[Path] = [default_config.path]
        projects_dirs: list[Path] = []
        for candidate in (
            default_config.root / "projects",
            default_config.root.parent,
            default_config.path.parent.parent,
        ):
            if candidate.name == "projects" or (candidate / "projects").exists():
                projects_dirs.append(
                    candidate if candidate.name == "projects" else candidate / "projects"
                )
        for projects_dir in projects_dirs:
            if projects_dir.is_dir():
                paths.extend(sorted(project / "pipeline.yaml" for project in projects_dir.iterdir() if (project / "pipeline.yaml").is_file()))
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(resolved)
        return unique

    @staticmethod
    def _books(config: PipelineConfig) -> list[int]:
        books = config.data.get("source", {}).get("books", {})
        if not isinstance(books, dict):
            return [1]
        parsed = []
        for key in books:
            try:
                parsed.append(int(key))
            except (TypeError, ValueError):
                continue
        return sorted(parsed) or [1]

    def _discover(self, default_config: PipelineConfig) -> dict[str, ReviewProject]:
        projects: dict[str, ReviewProject] = {}
        for path in self._candidate_config_paths(default_config):
            try:
                config = default_config if path == default_config.path.resolve() else load_config(path)
            except ConfigurationError:
                continue
            project_id = config.project_id
            if project_id in projects:
                continue
            project = config.project
            projects[project_id] = ReviewProject(
                project_id=project_id,
                title=str(project.get("title") or project.get("description") or project_id),
                path=config.path,
                config=config,
                books=self._books(config),
            )
        return projects

    def repository(self, project_id: str, *, book: int, profile: str) -> ReviewRepository:
        project = self._projects.get(project_id)
        if project is None:
            raise ConfigurationError(f"Unknown review project: {project_id}")
        if book not in project.books:
            raise ConfigurationError(
                f"Project {project_id!r} has no configured book {book}"
            )
        return ReviewRepository(config=project.config, book=book, profile=profile)

    def to_api(self) -> dict[str, Any]:
        return {
            "default_project_id": self.default_project_id,
            "projects": [
                {
                    "id": project.project_id,
                    "title": project.title,
                    "path": str(project.path),
                    "books": project.books,
                    "task_type": project.config.task_type,
                    "source_label": project.config.source_label,
                    "target_label": project.config.target_label,
                }
                for project in sorted(
                    self._projects.values(), key=lambda item: item.title.casefold()
                )
            ],
        }


def start_review_server(
    config: PipelineConfig,
    *,
    book: int = 1,
    profile: str = "production",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> RunningReviewServer:
    server = _build_review_http_server(
        config,
        book=book,
        profile=profile,
        host=host,
        port=port,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="jerome-reviewer",
        daemon=True,
    )
    thread.start()
    return RunningReviewServer(server=server, thread=thread)


def _build_review_http_server(
    config: PipelineConfig,
    *,
    book: int,
    profile: str,
    host: str,
    port: int,
) -> ReviewHTTPServer:
    repository = ReviewRepository(config=config, book=book, profile=profile)
    return ReviewHTTPServer(
        (host, port),
        repository,
        ReviewProjectCatalog(config),
    )


def serve_review(
    config: PipelineConfig,
    *,
    book: int = 1,
    profile: str = "production",
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    server = _build_review_http_server(
        config,
        book=book,
        profile=profile,
        host=host,
        port=port,
    )
    actual_host, actual_port = server.server_address[:2]
    api_url = f"http://{actual_host}:{actual_port}/"

    vite_process = None
    if _npm_available() and (STATIC_ROOT / "package.json").exists():
        vite_process = _start_vite_dev(STATIC_ROOT)
        if vite_process is not None:
            ui_url = "http://localhost:5173/"
            print(f"Jerome Reviewer UI (Vite dev): {ui_url}", flush=True)
            print(f"Python API backend: {api_url}", flush=True)
            print("Press Ctrl+C to stop.", flush=True)
            if open_browser:
                webbrowser.open(ui_url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
                if vite_process is not None:
                    vite_process.terminate()
                    vite_process.wait(timeout=5)
            return

    url = api_url
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
