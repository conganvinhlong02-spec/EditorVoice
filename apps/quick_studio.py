"""EditorVoice - minimal local UI optimized for fast TTS testing.

Run with::

    python -m apps.quick_studio

The model is loaded once in a background thread. Audio is streamed as PCM WAV so
the browser can start playback before the whole sentence has been generated.
"""

from __future__ import annotations

import io
import json
import os
import sys
import asyncio
import tempfile
import threading
import time
import uuid
import wave
import webbrowser
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vieneu import Vieneu

from .quick_studio_audio import (
    MAX_SPEECH_SPEED,
    MIN_SPEECH_SPEED,
    pcm_wav_duration,
    time_stretch,
)


if sys.platform == "win32":
    # Windows PowerShell may redirect stdout using a legacy code page. Logging a
    # Vietnamese voice name must never be able to break an audio response.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


SAMPLE_RATE = 48_000
ROOT_DIR = Path(__file__).resolve().parents[1]
CLIENT_PATH = ROOT_DIR / "client" / "quick_studio.html"
CLIENT_ASSETS_DIR = ROOT_DIR / "client" / "assets"
VOICE_META_PATH = ROOT_DIR / "src" / "vieneu" / "assets" / "voices_v3_turbo.json"
APP_DATA_DIR = Path(os.getenv("VIENEU_APP_DATA_DIR", str(ROOT_DIR / ".quick-studio-data")))
CLONE_STORE_DIR = Path(
    os.getenv("VIENEU_CLONE_DIR", str(APP_DATA_DIR / "cloned_voices"))
)
HISTORY_STORE_DIR = APP_DATA_DIR / "history"
HISTORY_INDEX_PATH = HISTORY_STORE_DIR / "index.json"

app = FastAPI(title="EditorVoice", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=CLIENT_ASSETS_DIR), name="assets")


class SynthesisRequest(BaseModel):
    """Text synthesis payload sent in the request body so long scripts are safe."""

    text: str = Field(min_length=1)
    voice: Optional[str] = None
    clone_id: Optional[str] = Field(default=None, max_length=64)
    style: str = Field(default="tu_nhien", pattern="^(tu_nhien|tin_tuc|doc_truyen)$")
    speed: float = Field(default=1.0, ge=MIN_SPEECH_SPEED, le=MAX_SPEECH_SPEED)
    quality: str = Field(default="render", pattern="^(stream|render)$")


class CloneRenameRequest(BaseModel):
    """A safe, short display name for one locally stored cloned voice."""

    name: str = Field(min_length=1, max_length=60)


_tts = None
_generation_lock = threading.Lock()
_cloned_voices: OrderedDict[str, dict] = OrderedDict()
_clone_registry_lock = threading.Lock()
_voice_preview_cache: dict[str, bytes] = {}
_clone_preview_cache: dict[str, bytes] = {}
_history_records: list[dict] = []
_history_lock = threading.Lock()
MAX_CLONED_VOICES = 50
MAX_HISTORY_RECORDS = 20
MAX_HISTORY_AUDIO_BYTES = 64 * 1024 * 1024
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MIN_REFERENCE_SECONDS = 2.0
MAX_REFERENCE_SECONDS = 15.0
_model_state = {
    "phase": "loading",
    "message": "Đang chuẩn bị EditorVoice… Lần đầu có thể cần tải model.",
    "backend": "ONNX · CPU · INT8",
    "sample_rate": SAMPLE_RATE,
    "voices": 0,
    "started_at": time.time(),
}


def _voice_metadata() -> list[dict]:
    """Read voice labels without waiting for the model to initialize."""
    try:
        data = json.loads(VOICE_META_PATH.read_text(encoding="utf-8"))
        result = []
        for voice_id, voice in data.get("presets", {}).items():
            description = voice.get("description", "")
            result.append(
                {
                    "id": voice_id,
                    "name": voice_id,
                    "description": description,
                    "gender": voice.get("gender", ""),
                    "style": voice.get("style", "tu_nhien"),
                }
            )
        return result
    except Exception:
        return []


PRESET_VOICES = _voice_metadata()
_model_state["voices"] = len(PRESET_VOICES)


def _public_clone(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "duration": entry["duration"],
        "created_at": entry["created_at"],
        "denoised": bool(entry.get("denoised", True)),
        "saved": bool(entry.get("persistent", False)),
    }


def _clone_store_path(clone_id: str) -> Path:
    return CLONE_STORE_DIR / f"{clone_id}.npz"


def _is_valid_history_id(entry_id: str) -> bool:
    return len(entry_id) == 32 and all(character in "0123456789abcdef" for character in entry_id)


def _history_audio_path(entry_id: str) -> Path:
    return HISTORY_STORE_DIR / f"{entry_id}.wav"


def _public_history_entry(entry: dict) -> dict:
    """Return UI metadata while keeping the WAV file on local disk."""
    entry_id = entry["id"]
    return {
        "id": entry_id,
        "createdAt": entry["createdAt"],
        "text": entry["text"],
        "voiceName": entry["voiceName"],
        "source": entry["source"],
        "style": entry["style"],
        "speed": entry["speed"],
        "duration": entry["duration"],
        "mode": entry["mode"],
        "fileName": entry["fileName"],
        "audioUrl": f"/api/history/{entry_id}/audio",
    }


def _write_history_index(entries: list[dict]) -> None:
    """Commit the history manifest atomically so app shutdown cannot erase it."""
    HISTORY_STORE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".index-", suffix=".tmp", dir=HISTORY_STORE_DIR, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(entries, temp_file, ensure_ascii=False, separators=(",", ":"))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, HISTORY_INDEX_PATH)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _coerce_history_entry(raw: object) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    entry_id = str(raw.get("id", ""))
    if not _is_valid_history_id(entry_id) or not _history_audio_path(entry_id).is_file():
        return None
    try:
        created_at = float(raw["createdAt"])
        speed = float(raw["speed"])
        duration = float(raw["duration"])
    except (KeyError, TypeError, ValueError):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    return {
        "id": entry_id,
        "createdAt": created_at,
        "text": text,
        "voiceName": str(raw.get("voiceName", "Giọng đọc"))[:100],
        "source": str(raw.get("source", "preset"))[:32],
        "style": str(raw.get("style", "tu_nhien"))[:32],
        "speed": speed,
        "duration": max(0.0, duration),
        "mode": str(raw.get("mode", "render"))[:32],
        "fileName": f"editorvoice-{int(created_at)}.wav",
    }


def _load_persisted_history() -> None:
    """Recover history from the app-data directory on every desktop launch."""
    if not HISTORY_INDEX_PATH.exists():
        return
    try:
        source = json.loads(HISTORY_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Skipping invalid saved history: {exc}")
        return
    if not isinstance(source, list):
        return
    loaded = [entry for item in source if (entry := _coerce_history_entry(item)) is not None]
    loaded.sort(key=lambda item: item["createdAt"], reverse=True)
    loaded = loaded[:MAX_HISTORY_RECORDS]
    with _history_lock:
        _history_records[:] = loaded
    if loaded != source:
        try:
            _write_history_index(loaded)
        except OSError as exc:
            print(f"Could not refresh saved history index: {exc}")
    if loaded:
        print(f"Loaded {len(loaded)} saved history records.")


def _persist_clone(entry: dict) -> None:
    """Atomically save only the reusable voice features, never the source audio."""
    CLONE_STORE_DIR.mkdir(parents=True, exist_ok=True)
    target = _clone_store_path(entry["id"])
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{entry['id']}-", suffix=".tmp", dir=CLONE_STORE_DIR, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            np.savez_compressed(
                temp_file,
                speaker_emb=np.asarray(entry["voice"]["speaker_emb"], dtype=np.float32),
                codes=np.asarray(entry["voice"]["codes"], dtype=np.int64),
                name=np.asarray(entry["name"]),
                duration=np.asarray(entry["duration"], dtype=np.float32),
                created_at=np.asarray(entry["created_at"], dtype=np.float64),
                denoised=np.asarray(bool(entry.get("denoised", True))),
            )
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _load_persisted_clones() -> None:
    if not CLONE_STORE_DIR.exists():
        return
    loaded = []
    for path in sorted(CLONE_STORE_DIR.glob("*.npz")):
        clone_id = path.stem
        if len(clone_id) != 32 or not all(char in "0123456789abcdef" for char in clone_id):
            continue
        try:
            with np.load(path, allow_pickle=False) as data:
                loaded.append(
                    {
                        "id": clone_id,
                        "name": str(data["name"].item()),
                        "duration": round(float(data["duration"].item()), 2),
                        "created_at": float(data["created_at"].item()),
                        "denoised": bool(data["denoised"].item()),
                        "persistent": True,
                        "voice": {
                            "speaker_emb": np.asarray(data["speaker_emb"], dtype=np.float32),
                            "codes": np.asarray(data["codes"], dtype=np.int64),
                        },
                    }
                )
        except Exception as exc:
            print(f"Skipping invalid saved clone {path.name}: {exc}")
    loaded.sort(key=lambda item: item["created_at"])
    with _clone_registry_lock:
        for entry in loaded[-MAX_CLONED_VOICES:]:
            _cloned_voices[entry["id"]] = entry
    if loaded:
        print(f"Loaded {min(len(loaded), MAX_CLONED_VOICES)} saved cloned voices.")


_load_persisted_clones()
_load_persisted_history()


def _load_model() -> None:
    global _tts
    try:
        _model_state["message"] = "Đang nạp model ONNX int8 vào bộ nhớ…"
        _tts = Vieneu(
            mode="v3turbo",
            backend="onnx",
            precision="int8",
            threads=int(os.getenv("VIENEU_THREADS", "0")),
        )
        voices = _tts.list_preset_voices()
        _model_state.update(
            {
                "phase": "ready",
                "message": f"Sẵn sàng · {len(voices)} giọng · 48 kHz",
                "voices": len(voices),
                "load_seconds": round(time.time() - _model_state["started_at"], 1),
            }
        )
        print(f"EditorVoice ready with {len(voices)} voices.")
    except Exception as exc:  # noqa: BLE001 - expose a readable local error
        _model_state.update(
            {
                "phase": "error",
                "message": "Không thể nạp model. Kiểm tra kết nối mạng ở lần chạy đầu.",
                "detail": str(exc),
            }
        )
        print(f"EditorVoice model error: {exc}")


threading.Thread(target=_load_model, name="vieneu-model-loader", daemon=True).start()


@app.get("/")
async def index():
    if not CLIENT_PATH.exists():
        return Response("quick_studio.html not found", status_code=404)
    # The desktop host keeps a persistent WebView profile for user data. The shell
    # itself must never be cached, otherwise an updated installer can display an
    # older UI after restart.
    return FileResponse(
        CLIENT_PATH,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/favicon.ico")
async def favicon():
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
    <rect width='64' height='64' rx='18' fill='#14151a'/>
    <path d='M13 35h7l4-13 7 27 6-34 6 20h8' fill='none' stroke='#d8ff63' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/>
    </svg>"""
    return Response(svg, media_type="image/svg+xml")


@app.get("/api/status")
async def status():
    with _clone_registry_lock:
        clone_count = len(_cloned_voices)
        saved_clone_count = sum(bool(item.get("persistent")) for item in _cloned_voices.values())
    return JSONResponse(
        {**_model_state, "cloned_voices": clone_count, "saved_cloned_voices": saved_clone_count}
    )


@app.get("/api/voices")
async def voices():
    return PRESET_VOICES


@app.get("/api/clones")
async def cloned_voices():
    with _clone_registry_lock:
        entries = [_public_clone(item) for item in _cloned_voices.values()]
    return sorted(entries, key=lambda item: item["created_at"], reverse=True)


@app.patch("/api/clones/{clone_id}")
async def rename_cloned_voice(clone_id: str, payload: CloneRenameRequest):
    """Rename a saved clone without reprocessing or retaining its source audio."""
    if len(clone_id) != 32 or not all(char in "0123456789abcdef" for char in clone_id):
        raise HTTPException(status_code=400, detail="Mã giọng clone không hợp lệ.")
    clean_name = " ".join(payload.name.strip().split())[:60]
    if not clean_name:
        raise HTTPException(status_code=400, detail="Tên giọng không được để trống.")
    with _clone_registry_lock:
        entry = _cloned_voices.get(clone_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy giọng clone.")
        previous_name = entry["name"]
        entry["name"] = clean_name
        if entry.get("persistent"):
            try:
                _persist_clone(entry)
            except Exception as exc:
                entry["name"] = previous_name
                raise HTTPException(status_code=500, detail="Chưa thể lưu tên giọng mới.") from exc
        public_entry = _public_clone(entry)
    return public_entry


@app.delete("/api/clones/{clone_id}")
async def delete_cloned_voice(clone_id: str):
    if len(clone_id) != 32 or not all(char in "0123456789abcdef" for char in clone_id):
        raise HTTPException(status_code=400, detail="Mã giọng clone không hợp lệ.")
    with _clone_registry_lock:
        entry = _cloned_voices.pop(clone_id, None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng clone.")
    try:
        _clone_store_path(clone_id).unlink(missing_ok=True)
    except OSError as exc:
        with _clone_registry_lock:
            _cloned_voices[clone_id] = entry
        raise HTTPException(status_code=500, detail="Chưa thể xóa giọng đã lưu.") from exc
    _clone_preview_cache.pop(clone_id, None)
    return {"ok": True, "id": clone_id}


@app.get("/api/history")
async def list_voice_history():
    """List locally persisted recordings, newest first."""
    with _history_lock:
        records = [_public_history_entry(entry) for entry in _history_records]
    return JSONResponse(records)


@app.get("/api/history/{entry_id}/audio")
async def get_history_audio(entry_id: str):
    if not _is_valid_history_id(entry_id):
        raise HTTPException(status_code=400, detail="Mã lịch sử không hợp lệ.")
    with _history_lock:
        known = any(entry["id"] == entry_id for entry in _history_records)
    audio_path = _history_audio_path(entry_id)
    if not known or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy bản thu trong lịch sử.")
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"editorvoice-{entry_id}.wav",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/api/history")
async def save_voice_history(
    audio_file: UploadFile = File(...),
    text: str = Form(...),
    voice_name: str = Form(default="Giọng đọc"),
    source: str = Form(default="preset"),
    style: str = Form(default="tu_nhien"),
    speed: float = Form(default=1.0),
    duration: float = Form(default=0.0),
    mode: str = Form(default="render"),
):
    """Persist one completed WAV recording outside the embedded browser profile."""
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Nội dung bản thu đang trống.")
    if not np.isfinite(speed) or speed <= 0:
        raise HTTPException(status_code=400, detail="Thông tin bản thu không hợp lệ.")

    entry_id = uuid.uuid4().hex
    created_at = round(time.time() * 1000)
    HISTORY_STORE_DIR.mkdir(parents=True, exist_ok=True)
    target = _history_audio_path(entry_id)
    temporary = None
    byte_count = 0
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{entry_id}-", suffix=".tmp", dir=HISTORY_STORE_DIR, delete=False
        ) as temp_file:
            temporary = Path(temp_file.name)
            while True:
                chunk = await audio_file.read(1024 * 1024)
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > MAX_HISTORY_AUDIO_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Bản WAV vượt quá giới hạn lưu trữ 64 MB.",
                    )
                temp_file.write(chunk)
        try:
            actual_duration = pcm_wav_duration(temporary)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Tệp tải lên không phải bản WAV PCM hợp lệ.",
            ) from exc
        os.replace(temporary, target)
        temporary = None
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Chưa thể lưu bản thu vào máy.") from exc
    finally:
        await audio_file.close()
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)

    entry = {
        "id": entry_id,
        "createdAt": created_at,
        "text": clean_text,
        "voiceName": " ".join(voice_name.split())[:100] or "Giọng đọc",
        "source": source[:32],
        "style": style[:32],
        "speed": round(float(speed), 3),
        "duration": round(actual_duration, 3),
        "mode": mode[:32],
        "fileName": f"editorvoice-{created_at}.wav",
    }
    expired: list[dict] = []
    try:
        with _history_lock:
            records = [entry] + [item for item in _history_records if item["id"] != entry_id]
            expired = records[MAX_HISTORY_RECORDS:]
            records = records[:MAX_HISTORY_RECORDS]
            _write_history_index(records)
            _history_records[:] = records
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Chưa thể cập nhật lịch sử bản thu.") from exc

    for old_entry in expired:
        try:
            _history_audio_path(old_entry["id"]).unlink(missing_ok=True)
        except OSError:
            pass
    return JSONResponse(_public_history_entry(entry), status_code=201)


@app.delete("/api/history")
async def clear_voice_history():
    with _history_lock:
        removed = list(_history_records)
        try:
            _write_history_index([])
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Chưa thể xóa lịch sử bản thu.") from exc
        _history_records.clear()
    for entry in removed:
        try:
            _history_audio_path(entry["id"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True, "removed": len(removed)}


@app.delete("/api/history/{entry_id}")
async def delete_voice_history_entry(entry_id: str):
    if not _is_valid_history_id(entry_id):
        raise HTTPException(status_code=400, detail="Mã lịch sử không hợp lệ.")
    with _history_lock:
        removed = next((item for item in _history_records if item["id"] == entry_id), None)
        if removed is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản thu trong lịch sử.")
        records = [item for item in _history_records if item["id"] != entry_id]
        try:
            _write_history_index(records)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Chưa thể xóa lịch sử bản thu.") from exc
        _history_records[:] = records
    try:
        _history_audio_path(entry_id).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "id": entry_id}


def _pcm16(audio: np.ndarray) -> bytes:
    values = np.asarray(audio, dtype=np.float32)
    return (values * 32767).clip(-32768, 32767).astype("<i2").tobytes()


def _wav_bytes(audio: np.ndarray) -> bytes:
    """Encode a complete mono float32 waveform as a standard PCM16 WAV."""
    target = io.BytesIO()
    with wave.open(target, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(_pcm16(audio))
    return target.getvalue()


def _ensure_model_ready() -> None:
    if _model_state["phase"] == "error":
        raise HTTPException(status_code=500, detail=_model_state.get("detail", _model_state["message"]))
    if _model_state["phase"] != "ready" or _tts is None:
        raise HTTPException(status_code=503, detail="Model đang khởi động, vui lòng chờ.")


@app.get("/api/voices/{voice_id}/preview")
def preview_preset_voice(voice_id: str):
    """Render and cache a short phrase using the exact preset voice."""
    _ensure_model_ready()
    if voice_id not in {item["id"] for item in PRESET_VOICES}:
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng đọc.")
    cached = _voice_preview_cache.get(voice_id)
    if cached is not None:
        return Response(content=cached, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Ứng dụng đang tạo âm thanh khác. Hãy thử nghe lại sau một chút.")
    try:
        audio = _tts.infer(
            "Xin chào, mời bạn nghe thử giọng đọc này.",
            voice=voice_id,
            style="tu_nhien",
            max_chars=256,
            apply_watermark=True,
        )
        if audio is None or len(audio) == 0:
            raise RuntimeError("Model chưa trả về âm thanh nghe thử.")
        payload = _wav_bytes(audio)
        _voice_preview_cache[voice_id] = payload
        return Response(
            content=payload,
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _generation_lock.release()


@app.get("/api/clones/{clone_id}/preview")
def preview_cloned_voice(clone_id: str):
    """Render and cache a short phrase using one saved cloned voice."""
    _ensure_model_ready()
    if len(clone_id) != 32 or not all(char in "0123456789abcdef" for char in clone_id):
        raise HTTPException(status_code=400, detail="Mã giọng clone không hợp lệ.")
    with _clone_registry_lock:
        entry = _cloned_voices.get(clone_id)
    if entry is None or not entry.get("persistent"):
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng clone đã lưu.")
    cached = _clone_preview_cache.get(clone_id)
    if cached is not None:
        return Response(
            content=cached,
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="Ứng dụng đang tạo âm thanh khác. Hãy thử nghe lại sau một chút.",
        )
    try:
        audio = _tts.infer(
            "Xin chào, đây là bản nghe thử của giọng đã lưu này.",
            voice=entry["voice"],
            style="tu_nhien",
            max_chars=256,
            apply_watermark=True,
        )
        if audio is None or len(audio) == 0:
            raise RuntimeError("Model chưa trả về âm thanh nghe thử.")
        payload = _wav_bytes(audio)
        _clone_preview_cache[clone_id] = payload
        return Response(
            content=payload,
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _generation_lock.release()


def _resolve_voice(voice: Optional[str], clone_id: Optional[str]):
    """Return the preset name/custom voice dict and a short log label."""
    if clone_id:
        with _clone_registry_lock:
            entry = _cloned_voices.get(clone_id)
            if entry is not None:
                _cloned_voices.move_to_end(clone_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Giọng clone không còn trong phiên. Hãy tải lại mẫu giọng.")
        return entry["voice"], f"clone:{entry['name']}"
    if voice and PRESET_VOICES and voice not in {item["id"] for item in PRESET_VOICES}:
        raise HTTPException(status_code=400, detail="Giọng đọc không hợp lệ.")
    return voice or None, voice or "default"


@app.post("/api/clone")
async def clone_voice(
    audio_file: UploadFile = File(...),
    voice_name: str = Form(default="Giọng clone"),
    denoise: bool = Form(default=False),
    save_voice: bool = Form(default=True),
):
    """Enroll one reference clip and optionally retain its features across restarts."""
    _ensure_model_ready()
    with _clone_registry_lock:
        if len(_cloned_voices) >= MAX_CLONED_VOICES:
            raise HTTPException(
                status_code=409,
                detail=f"Thư viện đã đủ {MAX_CLONED_VOICES} giọng. Hãy xóa bớt một giọng cũ.",
            )
    filename = audio_file.filename or "reference.wav"
    suffix = Path(filename).suffix.lower() or ".wav"
    if suffix not in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}:
        raise HTTPException(status_code=400, detail="Định dạng chưa hỗ trợ. Hãy dùng WAV, MP3, FLAC, M4A hoặc OGG.")

    payload = await audio_file.read(MAX_REFERENCE_BYTES + 1)
    await audio_file.close()
    if not payload:
        raise HTTPException(status_code=400, detail="Tệp âm thanh đang trống.")
    if len(payload) > MAX_REFERENCE_BYTES:
        raise HTTPException(status_code=413, detail="Tệp mẫu quá lớn. Giới hạn là 20 MB.")

    try:
        info = sf.info(io.BytesIO(payload))
        duration = float(info.duration)
        probe, _ = sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)
        probe = np.asarray(probe, dtype=np.float32)
        peak = float(np.max(np.abs(probe))) if probe.size else 0.0
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Không đọc được tệp âm thanh. WAV hoặc FLAC sẽ ổn định nhất.") from exc
    if duration < MIN_REFERENCE_SECONDS:
        raise HTTPException(status_code=400, detail="Mẫu giọng quá ngắn. Hãy dùng đoạn nói từ 2 đến 15 giây.")
    if duration > MAX_REFERENCE_SECONDS:
        raise HTTPException(status_code=400, detail="Mẫu giọng quá dài. Hãy cắt xuống tối đa 15 giây.")
    if peak < 0.003:
        raise HTTPException(status_code=400, detail="Mẫu giọng quá nhỏ hoặc không có tiếng nói rõ ràng.")
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Ứng dụng đang bận tạo âm thanh. Hãy chờ một chút rồi thử lại.")

    temp_path = None
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(prefix="editorvoice-clone-", suffix=suffix, delete=False) as temp_file:
            temp_file.write(payload)
            temp_path = Path(temp_file.name)
        speaker_emb, ref_codes = await asyncio.to_thread(
            _tts.encode_reference,
            temp_path,
            denoise=denoise,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chưa thể clone mẫu giọng này: {exc}") from exc
    finally:
        _generation_lock.release()
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    clean_name = " ".join(voice_name.strip().split())[:60] or "Giọng clone"
    clone_id = uuid.uuid4().hex
    entry = {
        "id": clone_id,
        "name": clean_name,
        "duration": round(duration, 2),
        "created_at": time.time(),
        "denoised": denoise,
        "persistent": save_voice,
        "voice": {
            "speaker_emb": np.asarray(speaker_emb, dtype=np.float32),
            "codes": np.asarray(ref_codes, dtype=np.int64),
        },
    }
    if save_voice:
        try:
            await asyncio.to_thread(_persist_clone, entry)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Đã clone nhưng chưa lưu được giọng: {exc}") from exc
    with _clone_registry_lock:
        _cloned_voices[clone_id] = entry
    elapsed = time.perf_counter() - started
    print(f"Enrolled clone '{clean_name}' from {duration:.2f}s in {elapsed:.2f}s.")
    return {
        "id": clone_id,
        "name": clean_name,
        "duration": round(duration, 2),
        "elapsed_ms": round(elapsed * 1000),
        "denoised": denoise,
        "saved": save_voice,
    }


@app.post("/api/stream")
async def stream_audio(request: SynthesisRequest):
    text = request.text
    voice = request.voice
    clone_id = request.clone_id
    style = request.style
    speed = request.speed
    if _model_state["phase"] == "error":
        raise HTTPException(status_code=500, detail=_model_state.get("detail", _model_state["message"]))
    if _model_state["phase"] != "ready" or _tts is None:
        raise HTTPException(status_code=503, detail="Model đang khởi động, vui lòng chờ.")
    voice_ref, voice_label = _resolve_voice(voice, clone_id)
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Đang tạo một bản thu khác. Vui lòng chờ hoặc bấm dừng.")

    cleaned_text = text.strip()
    if not cleaned_text:
        _generation_lock.release()
        raise HTTPException(status_code=400, detail="Nội dung đang trống.")

    def generate():
        started = time.perf_counter()
        samples = 0
        try:
            for chunk in _tts.infer_stream(
                cleaned_text,
                voice=voice_ref,
                style=style,
                max_chars=256,
                apply_watermark=True,
            ):
                if chunk is None or len(chunk) == 0:
                    continue
                chunk = time_stretch(chunk, speed, SAMPLE_RATE)
                samples += len(chunk)
                yield _pcm16(chunk)
        finally:
            elapsed = time.perf_counter() - started
            duration = samples / SAMPLE_RATE
            realtime_factor = duration / elapsed if elapsed else 0
            print(
                f"Generated {duration:.2f}s audio in {elapsed:.2f}s "
                f"({realtime_factor:.2f}x realtime) · voice={voice_label} · style={style} "
                f"· speech_speed={speed:.2f}x"
            )
            _generation_lock.release()

    return StreamingResponse(
        generate(),
        # Raw PCM avoids a fake RIFF size in the streaming header. The browser
        # schedules chunks immediately, then writes an exact WAV header at EOF.
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-EditorVoice-Sample-Rate": str(SAMPLE_RATE),
            "X-EditorVoice-Backend": "onnx-int8",
            "X-EditorVoice-Speech-Speed": f"{speed:.2f}",
        },
    )


@app.post("/api/render")
def render_audio(request: SynthesisRequest):
    """Render the full waveform before returning one exact, downloadable WAV."""
    text = request.text
    voice = request.voice
    clone_id = request.clone_id
    style = request.style
    speed = request.speed
    if _model_state["phase"] == "error":
        raise HTTPException(status_code=500, detail=_model_state.get("detail", _model_state["message"]))
    if _model_state["phase"] != "ready" or _tts is None:
        raise HTTPException(status_code=503, detail="Model đang khởi động, vui lòng chờ.")
    voice_ref, voice_label = _resolve_voice(voice, clone_id)
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Đang tạo một bản thu khác. Vui lòng chờ hoặc bấm dừng.")

    cleaned_text = text.strip()
    if not cleaned_text:
        _generation_lock.release()
        raise HTTPException(status_code=400, detail="Nội dung đang trống.")

    started = time.perf_counter()
    try:
        sampling = {
            "temperature": 0.65,
            "top_k": 20,
            "top_p": 0.90,
            "repetition_penalty": 1.15,
        }
        audio = _tts.infer(
            cleaned_text,
            voice=voice_ref,
            style=style,
            max_chars=256,
            apply_watermark=True,
            **sampling,
        )
        if audio is None or len(audio) == 0:
            raise RuntimeError("Model chưa trả về âm thanh.")
        audio = time_stretch(audio, speed, SAMPLE_RATE)
        elapsed = time.perf_counter() - started
        duration = len(audio) / SAMPLE_RATE
        payload = _wav_bytes(audio)
        realtime_factor = duration / elapsed if elapsed else 0
        print(
            f"Rendered {duration:.2f}s audio in {elapsed:.2f}s "
            f"({realtime_factor:.2f}x realtime) · voice={voice_label} · style={style} "
            f"· speech_speed={speed:.2f}x"
        )
        return Response(
            content=payload,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'inline; filename="editorvoice-render.wav"',
                "X-EditorVoice-Sample-Rate": str(SAMPLE_RATE),
                "X-EditorVoice-Elapsed-Ms": str(round(elapsed * 1000)),
                "X-EditorVoice-Duration-Ms": str(round(duration * 1000)),
                "X-EditorVoice-Backend": "onnx-int8",
                "X-EditorVoice-Speech-Speed": f"{speed:.2f}",
                "X-EditorVoice-Quality": "render-podcast",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _generation_lock.release()


@app.get("/api/health")
async def health():
    code = 200 if _model_state["phase"] in {"loading", "ready"} else 500
    return JSONResponse({"ok": code == 200, "phase": _model_state["phase"]}, status_code=code)


def _open_browser(port: int) -> None:
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main() -> None:
    port = int(os.getenv("VIENEU_PORT", "7860"))
    if os.getenv("VIENEU_NO_BROWSER", "0") != "1":
        threading.Thread(target=_open_browser, args=(port,), daemon=True).start()
    print(f"EditorVoice: http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
