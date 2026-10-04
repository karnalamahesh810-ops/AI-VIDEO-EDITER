"""
The voice endpoint as a RunPod queue (serverless) worker.

RunPod's /run and /runsync carry JSON only, so the audio goes back base64:

    input : {model, voice, input, response_format, speed, reference_audio?, ...}
            (the same fields as POST /v1/audio/speech; {"action": "health"}
            answers what is loaded)
    output: {"audio_base64", "format", "content_type", "seconds", "sample_rate",
             "gpu_seconds", "model", "voice"}
        or  {"refused": "why"} for a request that can never work (an unknown
            voice, Chatterbox not in this image) - the job still COMPLETES, so
            the video worker (runpod/src/tts.py) does not ask again.

Anything else that goes wrong raises: RunPod marks the job FAILED and the
video worker asks again on another attempt. One part of a narration is at
most ~1,500 characters (~100 s, ~2.5 MB as FLAC), far under RunPod's 20 MB
answer limit - ask for flac or mp3, not wav, to keep it that way.
"""
import base64

try:                                    # as a package (the tests) ...
    from . import engines
except ImportError:                     # ... or as plain files in the image
    import engines


def handler(job: dict) -> dict:
    req = (job or {}).get("input") or {}
    # RunPod's OpenAI-style route (/openai/v1/...) hands the body over like this.
    if isinstance(req.get("openai_input"), dict):
        req = req["openai_input"]
    if req.get("action") == "health":
        return engines.health()
    try:
        out = engines.speak(req)
    except engines.Refused as e:
        return {"refused": str(e)}
    audio = out.pop("audio")
    return {"audio_base64": base64.b64encode(audio).decode("ascii"), **out}


if __name__ == "__main__":
    import runpod

    engines.preload()                   # the model is on the GPU before the first job
    runpod.serverless.start({"handler": handler})
