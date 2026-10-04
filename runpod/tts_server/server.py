"""
The voice endpoint as an HTTP server: OpenAI's speech API on our own voices.

    POST /v1/audio/speech   {model, voice, input, response_format, speed}
                            -> the audio itself (Content-Type by format)
    GET  /v1/audio/voices   the Kokoro voices in this image
    GET  /health            what is loaded, on which device, at which revisions
    GET  /ping              200 once the server answers (RunPod's load-balancer check)

Any client that speaks OpenAI's text-to-speech API can use it; the video
worker does (runpod/src/tts.py, TTS_API_BASE). Run it where an HTTP port is
reachable - a GPU pod, or a RunPod load-balancing endpoint (TTS_SERVE=http).
On a RunPod queue endpoint the same engines sit behind rp_handler.py instead.

With TTS_SERVER_KEY set, every speech request must carry
"Authorization: Bearer <key>"; without it the server trusts whatever stands
in front of it (RunPod checks its own API key before a request arrives).
"""
import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

try:                                    # as a package (the tests) ...
    from . import engines
except ImportError:                     # ... or as plain files in the image
    import engines


@asynccontextmanager
async def _lifespan(_app):
    # The model goes onto the GPU before the first request, not during it.
    if os.getenv("TTS_SKIP_PRELOAD", "") != "1":
        await run_in_threadpool(engines.preload)
    yield


app = FastAPI(title="ThumbGenius voice endpoint", docs_url=None, redoc_url=None, lifespan=_lifespan)


def _error(status: int, message: str, kind: str) -> JSONResponse:
    """OpenAI's error shape, so any OpenAI client shows the reason."""
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": kind}})


def _allowed(request: Request) -> bool:
    key = os.getenv("TTS_SERVER_KEY", "")
    if not key:
        return True
    sent = request.headers.get("authorization", "")
    return hmac.compare_digest(sent.encode(), f"Bearer {key}".encode())


@app.get("/ping")
def ping() -> dict:
    return {"status": "healthy"}


@app.get("/health")
def health() -> dict:
    return engines.health()


@app.get("/v1/audio/voices")
def voices() -> dict:
    return {"voices": engines.KOKORO.voices(), "default": engines.DEFAULT_VOICE,
            "chatterbox": engines.chatterbox_enabled()}


@app.get("/v1/models")
def models() -> dict:
    names = ["kokoro"] + (["chatterbox"] if engines.chatterbox_enabled() else [])
    return {"object": "list", "data": [{"id": n, "object": "model", "owned_by": "thumbgenius"} for n in names]}


@app.post("/v1/audio/speech")
async def speech(request: Request):
    if not _allowed(request):
        return _error(401, "missing or wrong API key", "authentication_error")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - not JSON at all
        return _error(400, "the request body must be JSON", "invalid_request_error")
    try:
        # The models are not async: one generation at a time, off the event loop.
        out = await run_in_threadpool(engines.speak, body)
    except engines.Refused as e:
        return _error(400, str(e), "invalid_request_error")
    except Exception as e:  # noqa: BLE001 - a failure worth the client's retry
        print(f"[tts] speech failed: {type(e).__name__}: {str(e)[:300]}", flush=True)
        return _error(500, f"{type(e).__name__}: {str(e)[:200]}", "server_error")
    return Response(content=out["audio"], media_type=out["content_type"], headers={
        "X-Audio-Seconds": str(out["seconds"]), "X-Gpu-Seconds": str(out["gpu_seconds"]),
        "X-Sample-Rate": str(out["sample_rate"]), "X-Model": out["model"], "X-Voice": out["voice"]})
