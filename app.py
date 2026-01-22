import os
import uuid
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Optional
from fastapi import FastAPI, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path("/tmp/rtsp_hls_demo")
BASE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Emotion Demo — UI + RTSP→HLS Backend")
app.mount("/hls", StaticFiles(directory=str(BASE_DIR)), name="hls")    # serve HLS output

workers: Dict[str, subprocess.Popen] = {}    # track running ffmpeg processes: id -> subprocess.Popen

def start_ffmpeg_hls(rtsp_url: str, out_dir: Path) -> subprocess.Popen:
        out_dir.mkdir(parents=True, exist_ok=True)
        # basic ffmpeg HLS command
        cmd = [
            "ffmpeg",
            "-rtsp_transport", "udp", #or udp also 
            "-i", rtsp_url,
            "-vf", "scale=w=640:h=-2",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-g", "30",
            "-sc_threshold", "0",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-f", "hls",
            "-hls_time", "1", # shorter segment duration
            "-hls_list_size", "3", # fewer segments in the playlist
            "-hls_flags", "delete_segments+append_list",
            str(out_dir / "index.m3u8"),
        ]
        # start process
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return p

@app.get("/", response_class=HTMLResponse)
def ui():
        with open("templates/front.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/start")
def start(rtsp: str = Body(..., embed=True)):
        if not rtsp.startswith("rtsp://"):
            raise HTTPException(status_code=400, detail="Invalid RTSP URL")
        sid = uuid.uuid4().hex
        out_dir = BASE_DIR / sid
        try:
            p = start_ffmpeg_hls(rtsp, out_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"ffmpeg start failed: {e}")
        workers[sid] = p
        return JSONResponse({"id": sid, "hls_url": f"/hls/{sid}/index.m3u8"})    # return relative path under /hls

@app.post("/stop")
def stop(id: str = Body(..., embed=True)):
        p = workers.get(id)
        if not p:
            raise HTTPException(status_code=404, detail="Stream id not found")
        try:
            p.terminate()
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        workers.pop(id, None)
        return JSONResponse({"stopped": id})    # optionally leave files for debugging; could delete here

@app.get("/status/{id}")
def status_endpoint(id: str):
        p = workers.get(id)
        running = p is not None and p.poll() is None
        return JSONResponse({"id": id, "running": running})
