from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import ConfigurationError, PROJECT_ROOT, get_cors_origins, get_settings
from app.llm_client import LLMError, generate_from_llm
from app.prompt_builder import build_prompt
from app.rule_engine import is_valid_output, normalize_output
from app.storage import init_db, save_prescript, get_recent_prescripts


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Prescript Pager", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/web", StaticFiles(directory=PROJECT_ROOT / "web"), name="web")


class PrescriptRequest(BaseModel):
    mode: Literal["ritual", "daily", "absurd"] = "ritual"


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/web/index.html")


@app.get("/health")
def health():
    """Configuration check only: no paid generation or upstream connectivity probe."""
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {
        "status": "configured", "provider": settings.provider,
        "model": settings.model, "timeout_seconds": settings.timeout_seconds,
    }


@app.post("/generate")
def generate_prescript(req: PrescriptRequest):
    try:
        settings = get_settings()
        history = get_recent_prescripts(limit=10)
        prompt = build_prompt(req.mode, history)
        raw = generate_from_llm(prompt, settings)
        text = normalize_output(raw)
        if not is_valid_output(text):
            raise LLMError("模型未返回有效中文指令，请重试或调整模型。")
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    prescript_id = save_prescript(text, req.mode)
    return {"id": prescript_id, "prescript": text, "mode": req.mode}
