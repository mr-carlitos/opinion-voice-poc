import logging
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.diagnostics import record_diagnostic
from app.export import OpinionSummary
from app.foundry import Foundry
from app.graph import Graph, GraphAuth, ServiceError, ensure_separate_folders
from app.grounding import load_corpus
from app.sessions import Session
from app.voice import bridge

STATIC_DIR = ROOT / "app/static"
settings = Settings.load()
browser_key = secrets.token_urlsafe(32)
auth = GraphAuth(settings) if not settings.graph_issues() else None
foundry = Foundry(settings) if settings.project_endpoint and settings.tenant_id else None
sessions: dict[str, Session] = {}
voice_sessions: set[str] = set()
logger = logging.getLogger(__name__)
app = FastAPI(title="Opinion Voice PoC", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
)


def same_origin(origin: str | None, host: str) -> bool:
    if not origin:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme == "http" and parsed.netloc == host


@app.middleware("http")
async def local_guard(request: Request, call_next):
    if request.method not in ("GET", "HEAD"):
        if (
            request.cookies.get("local_session") != browser_key
            or request.headers.get("x-local-client") != "1"
            or not same_origin(request.headers.get("origin"), request.headers.get("host", ""))
        ):
            return JSONResponse(
                status_code=403, content={"message": "Nur lokale Browseraktionen sind erlaubt."}
            )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(ServiceError)
async def service_error(request: Request, error: ServiceError):
    return JSONResponse(status_code=502, content={"message": str(error)})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, error: Exception):
    logger.error("Operation %s failed: %s", request.url.path, type(error).__name__)
    return JSONResponse(
        status_code=502,
        content={
            "message": f"Dienstaufruf fehlgeschlagen ({type(error).__name__}). "
            "Anmeldung, Endpunkte und Berechtigungen pruefen."
        },
    )


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/readiness")
def readiness() -> JSONResponse:
    issues = settings.issues()
    state = (
        auth.snapshot()
        if auth
        else {
            "status": "not_configured",
            "mode": settings.graph_auth_mode,
        }
    )
    return JSONResponse(
        status_code=503 if issues else 200,
        content={
            "ready": not issues and state["status"] == "signed_in",
            "code": "configuration_required" if issues else "configured",
            "message": "; ".join(issues)
            if issues
            else "Konfiguriert. Dienste werden beim Sitzungsstart geprueft.",
            "can_sign_in": auth is not None,
            "auth": state,
            "voice_delivery_mode": settings.voice_delivery_mode,
            "avatar_available": settings.avatar_enabled
            and settings.voice_delivery_mode == "streaming",
            "speech_independently_verified": settings.voice_delivery_mode == "strict",
        },
    )


@app.post("/api/auth/start")
def sign_in():
    if not auth:
        raise HTTPException(503, "Graph-Konfiguration fehlt oder ist ungueltig.")
    return auth.start()


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int


@app.get("/api/sessions/{session_id}/draft")
def draft_state(session_id: str):
    return get_session(session_id).snapshot()


@app.post("/api/sessions/{session_id}/editing")
def mark_editing(session_id: str, body: SaveRequest):
    session = get_session(session_id)
    return session.mark_editing(body.version)


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    avatar_enabled: bool = False


@app.post("/api/sessions")
def create_session(body: AvatarRequest | None = None):
    if settings.issues() or not auth or not auth.owner or not foundry:
        raise HTTPException(503, "Konfiguration und SharePoint-Verbindung erforderlich.")
    if len(sessions) >= 3:
        raise HTTPException(
            409, "Bitte eine vorhandene Sitzung loeschen; maximal drei lokale Sitzungen."
        )
    started = time.monotonic()
    avatar = bool(body and body.avatar_enabled)
    if avatar and (not settings.avatar_enabled or settings.voice_delivery_mode != "streaming"):
        raise HTTPException(400, "Avatar erfordert aktivierten Streaming-Modus.")
    with Graph(auth) as graph:
        source = graph.resolve_folder(
            settings.input_url, drive_id=settings.input_drive_id, item_id=settings.input_folder_id
        )
        output = graph.resolve_folder(
            settings.output_url,
            drive_id=settings.output_drive_id,
            item_id=settings.output_folder_id,
        )
        ensure_separate_folders(source, output)
        folders_done = time.monotonic()
        corpus = load_corpus(graph, source)
    corpus_done = time.monotonic()
    foundry.configure_agent()
    agent_done = time.monotonic()
    session = Session(auth.owner, foundry.create_conversation(corpus), corpus, output)
    session.avatar_enabled = avatar
    timings = {
        "folders": round(folders_done - started, 2),
        "corpus": round(corpus_done - folders_done, 2),
        "agent": round(agent_done - corpus_done, 2),
        "conversation": round(time.monotonic() - agent_done, 2),
        "total": round(time.monotonic() - started, 2),
    }
    logger.info("Session startup seconds: %s", timings)
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "sources": [source.model_dump(mode="json") for source in corpus.sources.values()],
        "versions": corpus.versions,
        "startup_seconds": timings,
        "limits": "30 Minuten / 30 Beitraege. Quellenstand vom Sitzungsstart.",
    }


def get_session(session_id: str) -> Session:
    session = sessions.get(session_id)
    if not session or not auth or not auth.owner or auth.owner["id"] != session.owner["id"]:
        raise HTTPException(404, "Sitzung nicht gefunden.")
    return session


class DraftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: OpinionSummary
    version: int


@app.post("/api/sessions/{session_id}/draft")
def edit_draft(session_id: str, body: DraftEdit):
    session = get_session(session_id)
    state = session.snapshot()
    if state["phase"] != "review" or state["frozen"] or state["version"] != body.version:
        raise HTTPException(409, "Der Entwurf wurde geaendert oder ist bereits eingefroren.")
    Foundry.check_sources(body.summary.sources, session.corpus)
    if not foundry:
        raise HTTPException(503, "Zusammenfassungspruefung ist nicht konfiguriert.")
    foundry.validate_summary(
        body.summary, session.corpus, list(session.user_turns), user_edited=True
    )
    return session.set_draft(body.summary, expected_version=body.version, validation_passed=True)


@app.post("/api/sessions/{session_id}/save")
def save(session_id: str, body: SaveRequest):
    session = get_session(session_id)
    with Graph(auth) as graph:
        return session.save(graph, body.version)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    session = get_session(session_id)
    if session.voice_connected:
        raise HTTPException(409, "Bitte zuerst die Verbindung stoppen.")
    foundry.delete_conversation(session.conversation_id)
    del sessions[session_id]
    voice_sessions.discard(session_id)
    return {"deleted": True, "message": "Gespeicherte SharePoint-Dateien bleiben erhalten."}


@app.websocket("/api/sessions/{session_id}/voice")
async def voice(socket: WebSocket, session_id: str):
    if socket.cookies.get("local_session") != browser_key or not same_origin(
        socket.headers.get("origin"), socket.headers.get("host", "")
    ):
        await socket.close(code=1008)
        return
    session = get_session(session_id)
    if session.voice_connected or session_id in voice_sessions:
        await socket.close(code=1008)
        return
    session.voice_connected = True
    try:
        await socket.accept()
        voice_sessions.add(session_id)
        await bridge(socket, session, settings, foundry, Graph(auth))
    except WebSocketDisconnect:
        pass
    except Exception as error:
        diagnostic_id = getattr(error, "diagnostic_id", None)
        if not diagnostic_id:
            diagnostic_id = record_diagnostic("voice_bridge_failure", error=error)
        try:
            await socket.send_json(
                {
                    "type": "error",
                    "diagnostic_id": diagnostic_id,
                    "message": f"Sprachverbindung fehlgeschlagen ({type(error).__name__}). "
                    f"Diagnose-ID: {diagnostic_id}. "
                    "Details im Terminal und .local/diagnostics.jsonl.",
                }
            )
        except Exception:
            pass
    finally:
        session.voice_connected = False
        try:
            await socket.close()
        except Exception:
            pass


@app.post("/api/exports")
def unavailable():
    return JSONResponse(
        status_code=409,
        content={"message": "Bitte zuerst den Sitzungsentwurf pruefen und freigeben."},
    )


@app.get("/")
def index() -> FileResponse:
    response = FileResponse(STATIC_DIR / "index.html")
    response.set_cookie("local_session", browser_key, httponly=True, samesite="strict")
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
