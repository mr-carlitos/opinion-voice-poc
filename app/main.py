from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(title="Opinion Voice PoC", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
)


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/readiness")
def readiness() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "ready": False,
            "code": "integrations_not_implemented",
            "message": "Voice Live und SharePoint sind noch nicht angebunden.",
        },
    )


@app.post("/api/sessions")
@app.post("/api/exports")
def unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "code": "integrations_not_implemented",
            "message": "Keine Sitzung gestartet und kein Dokument gespeichert.",
        },
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
