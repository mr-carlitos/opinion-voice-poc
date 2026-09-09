import logging
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.export import OpinionSummary
from app.foundry import Foundry
from app.graph import Graph, GraphAuth, ServiceError
from app.grounding import load_corpus
from app.sessions import Session
from app.voice import bridge

STATIC_DIR = ROOT / "app/static"
settings = Settings.load()
browser_key = secrets.token_urlsafe(32)
auth = GraphAuth(settings) if settings.tenant_id and settings.graph_client_id else None
foundry = Foundry(settings) if settings.project_endpoint and settings.tenant_id else None
sessions: dict[str, Session] = {}
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
        if request.cookies.get("local_session") != browser_key or request.headers.get("x-local-client") != "1" or not same_origin(request.headers.get("origin"), request.headers.get("host", "")):
            return JSONResponse(status_code=403, content={"message": "Nur lokale Browseraktionen sind erlaubt."})
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
    return JSONResponse(status_code=502, content={"message": f"Dienstaufruf fehlgeschlagen ({type(error).__name__}). Anmeldung, Endpunkte und Berechtigungen pruefen."})


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/readiness")
def readiness() -> JSONResponse:
    issues = settings.issues()
    state = auth.snapshot() if auth else {"status": "not_configured"}
    return JSONResponse(
        status_code=503 if issues else 200,
        content={
            "ready": not issues and state["status"] == "signed_in",
            "code": "configuration_required" if issues else "configured",
            "message": "; ".join(issues) if issues else "Konfiguriert. Dienste werden beim Sitzungsstart geprueft.",
            "can_sign_in": auth is not None, "auth": state,
        },
    )


@app.post("/api/auth/start")
def sign_in():
    if not auth:
        raise HTTPException(503, "AZURE_TENANT_ID und GRAPH_CLIENT_ID fehlen.")
    return auth.start()


@app.post("/api/sessions/{session_id}/editing")
def mark_editing(session_id: str):
    session = get_session(session_id)
    with session.lock:
        if session.document is not None:
            raise HTTPException(409, "Der freigegebene Entwurf ist bereits eingefroren.")
        session.draft_editing = True
    return {"editing": True}


@app.post("/api/sessions")
def create_session():
    if settings.issues() or not auth or not auth.owner or not foundry:
        raise HTTPException(503, "Konfiguration und Microsoft-365-Anmeldung erforderlich.")
    if len(sessions) >= 3:
        raise HTTPException(409, "Bitte eine vorhandene Sitzung loeschen; maximal drei lokale Sitzungen.")
    graph = Graph(auth)
    source = graph.resolve_folder(settings.input_url)
    output = graph.resolve_folder(settings.output_url)
    if source.drive_id == output.drive_id and source.item_id == output.item_id:
        raise ServiceError("Eingabe und Ausgabe zeigen auf denselben Ordner.")
    corpus = load_corpus(graph, source)
    foundry.configure_agent()
    session = Session(auth.owner, foundry.create_conversation(corpus), corpus, output)
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "sources": [source.model_dump(mode="json") for source in corpus.sources.values()],
        "versions": corpus.versions,
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


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int


@app.post("/api/sessions/{session_id}/draft")
def edit_draft(session_id: str, body: DraftEdit):
    session = get_session(session_id)
    if session.phase != "review":
        raise HTTPException(409, "Kein Entwurf in Pruefung.")
    Foundry.check_sources(body.summary.sources, session.corpus)
    session.set_draft(body.summary)
    return {"version": session.draft_version, "summary": session.draft.model_dump(mode="json")}


@app.post("/api/sessions/{session_id}/save")
def save(session_id: str, body: SaveRequest):
    session = get_session(session_id)
    return session.save(Graph(auth), body.version)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    session = get_session(session_id)
    if session.voice_connected:
        raise HTTPException(409, "Bitte zuerst die Verbindung stoppen.")
    foundry.delete_conversation(session.conversation_id)
    del sessions[session_id]
    return {"deleted": True, "message": "Gespeicherte SharePoint-Dateien bleiben erhalten."}


@app.websocket("/api/sessions/{session_id}/voice")
async def voice(socket: WebSocket, session_id: str):
    if socket.cookies.get("local_session") != browser_key or not same_origin(socket.headers.get("origin"), socket.headers.get("host", "")):
        await socket.close(code=1008)
        return
    session = get_session(session_id)
    if session.voice_connected:
        await socket.close(code=1008)
        return
    await socket.accept()
    session.voice_connected = True
    try:
        await bridge(socket, session, settings, foundry, Graph(auth))
    except WebSocketDisconnect:
        pass
    except Exception as error:
        logger.error("Voice bridge failed: %s", type(error).__name__)
        try:
            await socket.send_json({"type": "error", "message": f"Sprachverbindung fehlgeschlagen ({type(error).__name__}). Endpunkt, Rollen und Modell pruefen."})
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
