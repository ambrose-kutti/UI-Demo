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

function ensureSingleSource(newType){ if (current.type && current.type !== newType) clearPreview(); }    // helper: ensureSingleSource is defined earlier
    document.getElementById('urlInput').addEventListener('keydown', (e)=> { if (e.key === 'Enter') { e.preventDefault(); loadUrlBtn.click(); } });  // url enter triggers load
    // cleanup on unload: stop backend session if active
    window.addEventListener('beforeunload', ()=> {
        if (!currentRtspSession) return;
        try {
        navigator.sendBeacon('/stop', JSON.stringify({ id: currentRtspSession.id }));
        } catch(e){}
});
