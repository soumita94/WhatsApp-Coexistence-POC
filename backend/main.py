from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from routes import onboarding
from routes import webhook
from routes import whatsapp


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


app = FastAPI(
    title="AXIOM WhatsApp Coexistence POC",
    version="0.2.0",
    description=(
        "AXIOM platform — WhatsApp Business App + Cloud API coexistence "
        "via Meta Embedded Signup."
    ),
)


# ------------------------------------------------------------
# CORS
#
# Allows both http://localhost:8000 and http://127.0.0.1:8000
# because browsers treat these as distinct origins.
# ------------------------------------------------------------

_origins = [
    settings.frontend_origin,
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# API Routes
#
# Order matters: more specific prefixes before less specific.
# All API routes must be registered BEFORE the StaticFiles
# mount so FastAPI routes take priority.
# ------------------------------------------------------------

app.include_router(onboarding.router)  # /api/onboarding/*
app.include_router(webhook.router)     # /webhook
app.include_router(whatsapp.router)    # /api/whatsapp/send


# ------------------------------------------------------------
# Public frontend configuration
#
# SECURITY: only public, non-secret values returned here.
#   - meta_app_id      (public — needed by Facebook SDK)
#   - meta_config_id   (public — needed by FB.login config_id)
#   - meta_graph_version (public)
#
# NEVER return:
#   - meta_app_secret
#   - meta_system_user_access_token
#   - meta_webhook_verify_token
# ------------------------------------------------------------

@app.get("/api/config", tags=["Config"])
async def get_public_config():
    return {
        "meta_app_id": settings.meta_app_id,
        "meta_config_id": settings.meta_config_id,
        "meta_graph_version": settings.meta_graph_version,
    }


# ------------------------------------------------------------
# Health check
# ------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health():
    return {
        "status": "ok",
        "service": "axiom-whatsapp-coexistence-poc",
        "version": "0.2.0",
        "config_loaded": bool(settings.meta_app_id),
    }


# ------------------------------------------------------------
# Serve frontend (must be last — catches all unmatched paths)
# ------------------------------------------------------------

app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIR,
        html=True,
    ),
    name="frontend",
)