    # app.py
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

# serve HLS output
app.mount("/hls", StaticFiles(directory=str(BASE_DIR)), name="hls")

# track running ffmpeg processes: id -> subprocess.Popen
workers: Dict[str, subprocess.Popen] = {}

HTML = """
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Emotion Demo — Input Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        :root{ --bg:#f8f9fa; --card:#fff; --text:#212529; --muted:#6c757d; }
        .dark{ --bg:#0d1117; --card:#0f1720; --text:#e6eef6; --muted:#9aa6b2; }
        body{ background:var(--bg); color:var(--text); }
        .card{ background:var(--card); }
        .muted{ color:var(--muted); }
        .hidden{ display:none !important; }
        .preview-media{ max-height:480px; width:auto; border-radius:6px; }
        .preview-wrap{ min-height:160px; display:flex; align-items:center; justify-content:center; gap:12px; flex-direction:column; }
        #actionBar{ display:flex; gap:8px; align-items:center; margin-bottom:12px; }
    </style>
    </head>
    <body class="p-4">
    <div class="container">
        <div class="d-flex justify-content-between align-items-center mb-3">
        <h3 class="m-0">Emotion Demo — Input Panel</h3>
        <div class="form-check form-switch">
            <input id="themeSwitch" class="form-check-input" type="checkbox">
            <label id="themeLabel" class="form-check-label muted">Light</label>
        </div>
        </div>

        <div id="actionBar">
        <button id="toggleSettingsBtn" class="btn btn-sm btn-outline-secondary">Hide</button>
        <button id="backBtn" class="btn btn-sm btn-outline-primary hidden">Back</button>
        <button id="clearPreviewBtn" class="btn btn-sm btn-outline-danger">Clear</button>
        <div class="ms-auto text-muted small">Only one source allowed at a time</div>
        </div>

        <div id="settingsCard" class="card shadow-sm mb-3">
        <div class="card-body">
            <div class="row g-3">
            <div class="col-md-4">
                <div class="p-3 border rounded h-100 d-flex flex-column">
                <h6>1. Upload Image / Video</h6>
                <input id="fileInput" class="form-control mb-2" type="file" accept="image/*,video/*">
                <div class="small text-muted">Local preview shows immediately.</div>
                </div>
            </div>

            <div class="col-md-4">
                <div class="p-3 border rounded h-100 d-flex flex-column">
                <h6>2. From URL (image/video/YouTube)</h6>
                <input id="urlInput" class="form-control mb-2" type="url" placeholder="https://example.com/photo.jpg or https://youtu.be/ID">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="small text-muted">Paste direct media or page</div>
                    <button id="loadUrlBtn" class="btn btn-sm btn-outline-primary">Submit</button>
                </div>
                </div>
            </div>

            <div class="col-md-4">
                <div class="p-3 border rounded h-100 d-flex flex-column">
                <h6>3. RTSP URL (real-time)</h6>
                <input id="rtspInput" class="form-control mb-2" type="text" placeholder="rtsp://user:pass@192.168.1.100:554/stream">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="small text-muted">Click Set to start and play</div>
                    <div>
                    <button id="connectRtspBtn" class="btn btn-sm btn-outline-success">Set</button>
                    <button id="stopRtspBtn" class="btn btn-sm btn-outline-danger">Stop</button>
                    </div>
                </div>
                </div>
            </div>
            </div>

            <div class="mt-3 text-end">
            <button id="submitBtn" class="btn btn-primary">Submit</button>
            </div>
        </div>
        </div>

        <div id="outputArea" class="card shadow-sm">
        <div class="card-body">
            <h5 class="card-title mb-2">Preview / Status</h5>
            <div id="status" class="muted">Idle</div>
            <div id="previewContainer" class="mt-3 preview-wrap"><div class="text-muted">No preview</div></div>
        </div>
        </div>

    </div>

    <script>
    // minimal UI logic integrated with backend /start and /stop
    const fileInput = document.getElementById('fileInput');
    const urlInput = document.getElementById('urlInput');
    const loadUrlBtn = document.getElementById('loadUrlBtn');
    const rtspInput = document.getElementById('rtspInput');
    const connectRtspBtn = document.getElementById('connectRtspBtn');
    const stopRtspBtn = document.getElementById('stopRtspBtn');

    const previewContainer = document.getElementById('previewContainer');
    const status = document.getElementById('status');
    const settingsCard = document.getElementById('settingsCard');
    const toggleSettingsBtn = document.getElementById('toggleSettingsBtn');
    const backBtn = document.getElementById('backBtn');
    const clearPreviewBtn = document.getElementById('clearPreviewBtn');
    const submitBtn = document.getElementById('submitBtn');
    const themeSwitch = document.getElementById('themeSwitch');
    const themeLabel = document.getElementById('themeLabel');

    let current = { type: null, blobUrl: null, value: null, embed: null, contentType: null };
    let currentRtspSession = null;
    let hlsPlayer = null;
    let rtspVideoEl = null;

    // theme
    themeSwitch.addEventListener('change', ()=> {
        if (themeSwitch.checked) { document.body.classList.add('dark'); themeLabel.textContent='Dark'; }
        else { document.body.classList.remove('dark'); themeLabel.textContent='Light'; }
    });

    // helpers
    function clearPreview() {
        if (current.blobUrl) { try { URL.revokeObjectURL(current.blobUrl); } catch(e){} }
        current = { type: null, blobUrl: null, value: null, embed: null, contentType: null };
        cleanupHls();
        previewContainer.innerHTML = '<div class="text-muted">No preview</div>';
        status.textContent = 'Idle';
        fileInput.value = '';
    }

    function ensureSingleSource(newType) {
        if (current.type && current.type !== newType) clearPreview();
    }

    function showImage(src) {
        cleanupHls();
        previewContainer.innerHTML = '';
        const img = document.createElement('img');
        img.className = 'preview-media';
        img.src = src;
        img.onload = ()=> status.textContent = 'Preview loaded';
        img.onerror = ()=> status.textContent = 'Could not load image (CORS/invalid URL)';
        previewContainer.appendChild(img);
    }

    function showVideo(src, autoplay=false, muted=true) {
        cleanupHls();
        previewContainer.innerHTML = '';
        const v = document.createElement('video');
        v.className = 'preview-media';
        v.controls = true;
        v.muted = muted;
        v.src = src;
        if (autoplay) v.autoplay = true;
        v.onloadeddata = ()=> status.textContent = 'Preview loaded';
        v.onerror = ()=> status.textContent = 'Could not load video (CORS/invalid URL)';
        previewContainer.appendChild(v);
    }

    function showIframe(src) {
        cleanupHls();
        previewContainer.innerHTML = '';
        const ifr = document.createElement('iframe');
        ifr.className = 'preview-media';
        ifr.src = src;
        ifr.frameBorder = '0';
        ifr.allow = 'autoplay; encrypted-media';
        ifr.allowFullscreen = true;
        ifr.onload = ()=> status.textContent = 'Preview loaded (embedded)';
        previewContainer.appendChild(ifr);
    }

    // file input
    fileInput.addEventListener('change', ()=> {
        const f = fileInput.files[0];
        if (!f) return;
        ensureSingleSource('file');
        const url = URL.createObjectURL(f);
        current = { type:'file', blobUrl:url, value:f.name, embed:null, contentType: f.type || '' };
        if (f.type.startsWith('image/')) showImage(url);
        else if (f.type.startsWith('video/')) showVideo(url, true, true);
        else status.textContent = 'Unsupported file type';
    });

    // YouTube parse
    function parseYouTube(u) {
        try {
        const url = new URL(u);
        if (url.hostname.includes('youtu.be')) return { id: url.pathname.slice(1), start: url.searchParams.get('t') || url.hash.match(/t=(\\d+)/)?.[1] };
        if (url.hostname.includes('youtube.com')) return { id: url.searchParams.get('v'), start: url.searchParams.get('t') || url.hash.match(/t=(\\d+)/)?.[1] };
        } catch(e){}
        return null;
    }

    // load URL (fetch then fallback to direct src)
    loadUrlBtn.addEventListener('click', async ()=> {
        const u = urlInput.value.trim();
        if (!u) return alert('Enter a URL');
        ensureSingleSource('url');
        status.textContent = 'Fetching remote URL for preview...';

        const yt = parseYouTube(u);
        if (yt && yt.id) {
        const embed = `https://www.youtube.com/embed/${yt.id}${yt.start ? ('?start='+yt.start) : ''}`;
        current = { type:'url', blobUrl:null, value:u, embed, contentType: null };
        showIframe(embed);
        return;
        }

        try {
        const resp = await fetch(u, { mode:'cors' });
        if (!resp.ok) throw new Error('network');
        const ct = (resp.headers.get('content-type') || '').toLowerCase();
        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        current = { type:'url', blobUrl, value:u, embed:null, contentType: ct };
        if (ct.startsWith('image/')) { showImage(blobUrl); return; }
        if (ct.startsWith('video/')) { showVideo(blobUrl, true, true); return; }
        if (u.match(/\\.(jpg|jpeg|png|gif|webp)$/i)) { showImage(blobUrl); return; }
        if (u.match(/\\.(mp4|webm|ogg)$/i)) { showVideo(blobUrl,true,true); return; }
        URL.revokeObjectURL(blobUrl);
        status.textContent = 'Unsupported remote content-type: ' + ct;
        } catch(err) {
        status.textContent = 'Fetch blocked or failed; trying direct URL...';
        // fallback try image then video
        const img = new Image();
        img.className = 'preview-media';
        let triedVideo = false;
        img.onload = ()=> { previewContainer.innerHTML=''; previewContainer.appendChild(img); status.textContent='Preview loaded (direct URL)'; current = { type:'url', blobUrl:null, value:u, embed:null, contentType:'image/*' }; };
        img.onerror = ()=> {
            if (triedVideo) { status.textContent = 'Unable to preview URL'; return; }
            triedVideo = true;
            const v = document.createElement('video');
            v.className='preview-media'; v.controls=true; v.src = u;
            v.onloadeddata = ()=> { previewContainer.innerHTML=''; previewContainer.appendChild(v); status.textContent='Preview loaded (direct URL)'; current = { type:'url', blobUrl:null, value:u, embed:null, contentType:'video/*' }; };
            v.onerror = ()=> { status.textContent = 'Unable to preview URL (CORS/unsupported)'; };
        };
        img.src = u;
        }
    });

    // RTSP start/stop integration with backend
    async function startRtspBackendAndPlay(rtsp) {
        status.textContent = 'Starting RTSP...';
        try {
        const resp = await fetch('/start', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ rtsp }) });
        if (!resp.ok) {
            const err = await resp.json().catch(()=>null);
            throw new Error(err?.detail || 'start failed');
        }
        const data = await resp.json();
        if (!data?.hls_url || !data?.id) throw new Error('invalid response');
        currentRtspSession = { id: data.id, hls_url: data.hls_url };
        status.textContent = 'RTSP running, playing... id: ' + data.id;
        playHlsInPreview(data.hls_url);
        } catch(e) {
        status.textContent = 'RTSP start failed: ' + (e.message || e);
        }
    }

    async function stopRtspBackendSession() {
        if (!currentRtspSession) return;
        try {
        await fetch('/stop', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ id: currentRtspSession.id }) });
        } catch(e){}
        currentRtspSession = null;
        cleanupHls();
        previewContainer.innerHTML = '<div class="text-muted">No preview</div>';
        status.textContent = 'RTSP stopped';
    }

    function playHlsInPreview(hlsPath) {
        cleanupHls();
        rtspVideoEl = document.createElement('video');
        rtspVideoEl.className = 'preview-media';
        rtspVideoEl.controls = true;
        rtspVideoEl.muted = true;
        rtspVideoEl.autoplay = true;
        previewContainer.innerHTML = '';
        previewContainer.appendChild(rtspVideoEl);

        let playlist;
        try { playlist = new URL(hlsPath, window.location.origin).href; } catch(e) { playlist = window.location.origin + hlsPath; }

        if (rtspVideoEl.canPlayType('application/vnd.apple.mpegurl')) {
        rtspVideoEl.src = playlist; rtspVideoEl.play().catch(()=>{});
        } else if (window.Hls) {
        hlsPlayer = new Hls();
        hlsPlayer.loadSource(playlist);
        hlsPlayer.attachMedia(rtspVideoEl);
        hlsPlayer.on(Hls.Events.MANIFEST_PARSED, ()=> rtspVideoEl.play().catch(()=>{}));
        hlsPlayer.on(Hls.Events.ERROR, (e,data)=> { console.warn('HLS error', data); status.textContent = 'HLS error: '+(data?.details||data?.type||''); });
        } else {
        status.textContent = 'HLS.js not available';
        }
    }

    function cleanupHls() {
        try { if (hlsPlayer) { hlsPlayer.destroy(); hlsPlayer = null; } } catch(e){}
        try { if (rtspVideoEl) { rtspVideoEl.pause(); rtspVideoEl.remove(); rtspVideoEl = null; } } catch(e){}
    }

    // wire RTSP buttons
    connectRtspBtn.addEventListener('click', async ()=> {
        const r = rtspInput.value.trim();
        if (!r) return alert('Enter RTSP URL');
        ensureSingleSource('rtsp');
        current = { type:'rtsp', blobUrl:null, value:r, embed:null, contentType:null };
        await startRtspBackendAndPlay(r);
        backBtn.classList.remove('hidden');
    });

    stopRtspBtn.addEventListener('click', async ()=> {
        await stopRtspBackendSession();
        backBtn.classList.add('hidden');
    });

    // submit button hides settings and keeps preview; if RTSP not started yet, start it
    submitBtn.addEventListener('click', async ()=> {
        if (!current.type) return alert('Select one source first');
        settingsCard.classList.add('hidden');
        document.getElementById('toggleSettingsBtn').textContent='Show';
        backBtn.classList.remove('hidden');
        status.textContent = 'Submitted. Source: ' + (current.value || current.type);
        if (current.type === 'rtsp' && !currentRtspSession) await startRtspBackendAndPlay(current.value);
    });

    // Back, Clear, Hide
    backBtn.addEventListener('click', ()=> {
        settingsCard.classList.remove('hidden'); document.getElementById('toggleSettingsBtn').textContent='Hide'; backBtn.classList.add('hidden');
        // restore preview where possible
        if (current.type === 'file' && current.blobUrl) {
        if ((current.contentType || '').startsWith('image/')) showImage(current.blobUrl);
        else showVideo(current.blobUrl, true, true);
        } else if (current.type === 'url') {
        if (current.embed) showIframe(current.embed);
        else if (current.blobUrl) {
            if ((current.contentType||'').startsWith('image/')) showImage(current.blobUrl); else showVideo(current.blobUrl,true,true);
        } else { status.textContent = 'URL present — press Load to preview'; urlInput.value = current.value || ''; }
        } else if (current.type === 'rtsp') {
        rtspInput.value = current.value || '';
        if (currentRtspSession) playHlsInPreview(currentRtspSession.hls_url);
        } else status.textContent = 'Idle';
    });

    clearPreviewBtn.addEventListener('click', clearPreview);

    // toggle settings visibility
    toggleSettingsBtn.addEventListener('click', ()=> {
        const hidden = settingsCard.classList.toggle('hidden');
        toggleSettingsBtn.textContent = hidden ? 'Show' : 'Hide';
    });

    // helper: ensureSingleSource is defined earlier
    function ensureSingleSource(newType){ if (current.type && current.type !== newType) clearPreview(); }

    // url enter triggers load
    document.getElementById('urlInput').addEventListener('keydown', (e)=> { if (e.key === 'Enter') { e.preventDefault(); loadUrlBtn.click(); } });

    // cleanup on unload: stop backend session if active
    window.addEventListener('beforeunload', ()=> {
        if (!currentRtspSession) return;
        try {
        navigator.sendBeacon('/stop', JSON.stringify({ id: currentRtspSession.id }));
        } catch(e){}
    });

    </script>
    </body>
    </html>
    """

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
        return HTML

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
        # return relative path under /hls
        return JSONResponse({"id": sid, "hls_url": f"/hls/{sid}/index.m3u8"})

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
        # optionally leave files for debugging; could delete here
        return JSONResponse({"stopped": id})

@app.get("/status/{id}")
def status_endpoint(id: str):
        p = workers.get(id)
        running = p is not None and p.poll() is None
        return JSONResponse({"id": id, "running": running})
