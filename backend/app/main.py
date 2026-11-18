"""Ponto de entrada da API do PredictLab.

Execute com:  uvicorn app.main:app --reload  (a partir da pasta backend/)
Documentação interativa: http://localhost:8000/docs
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import analysis, datasets, ml, ops
from .config import APP_NAME, APP_VERSION
from .services.synthetic import build_demo_dataset
from .store import store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.add(build_demo_dataset(), persist=False)  # modo demonstração sempre disponível
    if os.getenv("PREDICTLAB_NO_PERSIST") != "1":
        store.load_persisted()
    yield


app = FastAPI(
    title=f"{APP_NAME} API",
    version=APP_VERSION,
    description="Plataforma educacional e experimental de monitoramento de equipamentos industriais "
                "e manutenção preditiva.",
    lifespan=lifespan,
)

origins = os.getenv("PREDICTLAB_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins], allow_methods=["*"],
                   allow_headers=["*"])

for r in (datasets.router, analysis.router, ml.router, ops.router):
    app.include_router(r)


@app.get("/api/health", tags=["sistema"])
def health():
    return {"status": "ok", "app": APP_NAME, "versao": APP_VERSION, "datasets": len(store.list())}


# Se o frontend foi compilado (frontend/dist), a API também o serve — útil para
# rodar tudo com um único comando.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
