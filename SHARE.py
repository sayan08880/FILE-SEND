import http.server
import urllib.parse
import html
import mimetypes
import json
import sys
import socket
import re
import threading
import webbrowser
import time
from pathlib import Path
from email import message_from_bytes
from email.policy import HTTP
import io

# ── Config ────────────────────────────────────────────────────────────────────
PREFERRED_PORT = 8080
SHARE_DIR = Path("./shared_files")
SHARE_DIR.mkdir(exist_ok=True)

# ── Utilities ─────────────────────────────────────────────────────────────────
def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def find_free_port(start: int = PREFERRED_PORT) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port found in range {start}-{start+19}")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def file_type_label(name: str) -> str:
    ext = Path(name).suffix.lower()
    groups = {
        "PDF": [".pdf"],
        "Word": [".doc", ".docx"],
        "Text": [".txt", ".md", ".log"],
        "ZIP": [".zip", ".tar", ".gz", ".rar", ".7z"],
        "Image": [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif"],
        "Video": [".mp4", ".mov", ".avi", ".mkv", ".webm"],
        "Audio": [".mp3", ".wav", ".flac", ".ogg", ".m4a"],
        "Code": [".py", ".js", ".ts", ".html", ".css", ".json", ".sh", ".bat", ".c", ".cpp", ".rs", ".go"],
        "Sheet": [".xls", ".xlsx", ".csv"],
        "Slide": [".ppt", ".pptx"],
        "App": [".exe", ".apk", ".dmg"],
    }
    for label, exts in groups.items():
        if ext in exts:
            return label
    return ext.lstrip(".").upper() or "File"


def parse_multipart(headers, body: bytes) -> list:
    """Parse multipart/form-data without cgi module."""
    content_type = headers.get("Content-Type", "")
    m = re.search(r'boundary=([^\s;]+)', content_type)
    if not m:
        return []

    fake_email = (
        f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n"
    ).encode() + body

    msg = message_from_bytes(fake_email, policy=HTTP)
    result = []

    if msg.is_multipart():
        for part in msg.get_payload():
            disp = part.get("Content-Disposition", "")
            name_m = re.search(r'name="([^"]*)"', disp)
            fname_m = re.search(r'filename="([^"]*)"', disp)
            if name_m:
                result.append((
                    name_m.group(1),
                    fname_m.group(1) if fname_m else None,
                    part.get_payload(decode=True) or b"",
                ))
    return result


# ── QR Code ───────────────────────────────────────────────────────────────────
def _qr_svg(url: str, size: int = 180) -> str:
    try:
        import segno
        import io
        import html

        qr = segno.make(url, error='h')

        buf = io.BytesIO()
        qr.save(
            buf,
            kind='svg',
            scale=4.8,
            border=0,
            dark='black',
            light='white',
            xmldecl=False
        )

        # ✅ DO NOT modify viewBox
        # Just return SVG as-is
        svg = buf.getvalue().decode('utf-8')

        # Optional: inject width & height safely (no viewBox change)
        svg = svg.replace(
            "<svg",
            f'<svg width="{size}" height="{size}"',
            1
        )

        return svg

    except Exception:
        # Fallback (no change needed here)
        safe_url = html.escape(url)
        return (
            f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
            f'<rect width="100%" height="100%" fill="#0f1117" rx="10"/>'
            f'<text x="50%" y="44%" text-anchor="middle" fill="#5eead4" '
            f'font-family="monospace" font-size="11" font-weight="bold">Scan or type:</text>'
            f'<text x="50%" y="62%" text-anchor="middle" fill="#fff" '
            f'font-family="monospace" font-size="9">{safe_url}</text>'
            f'</svg>'
        )


# ── File list HTML ────────────────────────────────────────────────────────────
def render_file_list_html() -> tuple[str, int]:
    try:
        entries = sorted(
            (f for f in SHARE_DIR.iterdir() if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        entries = []

    if not entries:
        return (
            '<div class="empty">'
            '<div class="empty-icon">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'
            '</svg>'
            '</div>'
            '<p>No files yet — upload something above</p>'
            '</div>'
        ), 0

    rows = []
    for f in entries:
        enc = urllib.parse.quote(f.name)
        safe = html.escape(f.name)
        jsafe = safe.replace("'", "\\'")
        ftype = file_type_label(f.name)
        size_str = human_size(f.stat().st_size)

        rows.append(
            f'<li class="fitem">'
            f'<span class="ftype-badge">{html.escape(ftype)}</span>'
            f'<div class="finfo">'
            f'<div class="fn" title="{safe}">{safe}</div>'
            f'<div class="fs">{size_str}</div>'
            f'<div class="rename-wrap">'
            f'<input class="rename-input" type="text" value="{safe}"/>'
            f'<button class="btn btn-ghost" onclick="submitRename(this, \'{jsafe}\')">Save</button>'
            f'<button class="btn btn-ghost" onclick="cancelRename(this)">Cancel</button>'
            f'</div>'
            f'</div>'
            f'<div class="btn-group">'
            f'<a class="btn btn-dl" href="/download/{enc}" download>Download</a>'
            f'<button class="btn btn-ghost" onclick="startRename(this, \'{jsafe}\')">Rename</button>'
            f'<button class="btn btn-danger" onclick="deleteFile(\'{jsafe}\')">Delete</button>'
            f'</div>'
            f'</li>'
        )

    return f'<ul class="flist">{"".join(rows)}</ul>', len(rows)


# ── HTML Template ─────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>FileBeam</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
:root {
  --bg:#080b10; --bg2:#0d1117; --surface:#111620; --surface2:#171d2b;
  --border:#1e2535; --border2:#2a3348;
  --accent:#5eead4; --accent2:#818cf8; --danger:#f87171;
  --text:#e2e8f0; --muted:#64748b; --muted2:#94a3b8; --ok:#4ade80;
  --mono:'IBM Plex Mono',monospace; --sans:'Instrument Sans',sans-serif;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;-webkit-font-smoothing:antialiased}
body::before{content:'';position:fixed;inset:0;z-index:0;
  background-image:linear-gradient(rgba(94,234,212,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(94,234,212,.04) 1px,transparent 1px);
  background-size:48px 48px;pointer-events:none}
body::after{content:'';position:fixed;inset:0;z-index:0;
  background:radial-gradient(ellipse 60% 40% at 70% 10%,rgba(129,140,248,.07) 0%,transparent 70%),
             radial-gradient(ellipse 50% 35% at 10% 80%,rgba(94,234,212,.06) 0%,transparent 70%);
  pointer-events:none}
.wrap{position:relative;z-index:1;max-width:900px;margin:0 auto;padding:48px 24px 64px}
header{display:flex;align-items:center;gap:16px;margin-bottom:40px}
.logo-mark{width:44px;height:44px;flex-shrink:0;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:12px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 32px rgba(94,234,212,.25)}
.logo-mark svg{width:22px;height:22px}
.logo-text h1{font-size:1.6rem;font-weight:700;letter-spacing:-.03em;color:#fff}
.logo-text .sub{font-family:var(--mono);font-size:.65rem;color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-top:2px}
.flash{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:10px;font-size:.84rem;font-weight:500;margin-bottom:22px;animation:fadein .3s ease}
@keyframes fadein{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
.flash.ok{background:rgba(74,222,128,.08);border:1px solid rgba(74,222,128,.2);color:var(--ok)}
.flash.err{background:rgba(248,113,113,.08);border:1px solid rgba(248,113,113,.2);color:var(--danger)}
.flash-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.flash.ok .flash-dot{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.flash.err .flash-dot{background:var(--danger);box-shadow:0 0 8px var(--danger)}
.phone-banner{background:var(--surface);border:1px solid var(--border2);border-radius:20px;padding:24px 28px;margin-bottom:24px;display:flex;align-items:center;gap:28px;flex-wrap:wrap;position:relative;overflow:hidden}
.phone-banner::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--accent),var(--accent2),transparent);opacity:.5}
.qr-wrap{flex-shrink:0;background:#fff;border-radius:12px;padding:8px;line-height:0}
.qr-wrap svg{display:block;border-radius:6px;}
.phone-info .label{font-family:var(--mono);font-size:.63rem;color:var(--accent);letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px}
.phone-url{font-family:var(--mono);font-size:1rem;font-weight:600;color:#fff;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;padding:10px 14px;display:inline-block;letter-spacing:.02em;word-break:break-all;margin-bottom:12px}
.phone-steps{font-size:.82rem;color:var(--muted2);line-height:1.9}
.phone-steps b{color:var(--text);font-weight:500}
.step-num{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:rgba(94,234,212,.12);border:1px solid rgba(94,234,212,.3);font-family:var(--mono);font-size:.62rem;color:var(--accent);margin-right:6px;vertical-align:middle}
.card{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:28px 26px;margin-bottom:22px;position:relative;overflow:hidden}
.card-title{font-family:var(--mono);font-size:.68rem;color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.card-title .count-badge{background:var(--surface2);border:1px solid var(--border2);color:var(--muted2);font-size:.65rem;padding:2px 9px;border-radius:20px}
.dropzone{border:1.5px dashed var(--border2);border-radius:14px;padding:40px 24px;text-align:center;cursor:pointer;transition:all .2s;position:relative;margin-bottom:16px}
.dropzone:hover,.dropzone.over{border-color:var(--accent);background:rgba(94,234,212,.04)}
.dropzone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.dz-icon{width:48px;height:48px;margin:0 auto 12px;background:var(--surface2);border:1px solid var(--border2);border-radius:12px;display:flex;align-items:center;justify-content:center}
.dz-icon svg{width:22px;height:22px;color:var(--accent)}
.dz-title{font-size:.95rem;font-weight:600;color:var(--text);margin-bottom:5px}
.dz-sub{font-size:.8rem;color:var(--muted)}
#file-names{font-family:var(--mono);font-size:.73rem;color:var(--accent2);margin-top:10px;min-height:18px;text-align:center}
#prog-wrap{display:none;margin-bottom:14px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;overflow:hidden;height:8px}
#prog-bar{height:100%;width:0%;transition:width .15s;background:linear-gradient(90deg,var(--accent),var(--accent2))}
#prog-label{font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-bottom:8px;display:none;text-align:right}
.btn{display:inline-flex;align-items:center;gap:8px;font-family:var(--sans);font-size:.875rem;font-weight:600;border:none;border-radius:10px;cursor:pointer;transition:all .15s;text-decoration:none}
.btn-primary{background:var(--accent);color:#0a0d14;padding:11px 26px;box-shadow:0 4px 20px rgba(94,234,212,.25)}
.btn-primary:hover{opacity:.88;transform:translateY(-1px);box-shadow:0 6px 28px rgba(94,234,212,.35)}
.btn-primary:active{transform:none}
.btn-ghost{background:transparent;border:1px solid var(--border2);color:var(--muted2);padding:7px 14px;font-size:.76rem}
.btn-ghost:hover{border-color:var(--accent2);color:var(--accent2)}
.btn-danger{background:transparent;border:1px solid rgba(248,113,113,.25);color:var(--danger);padding:7px 14px;font-size:.76rem}
.btn-danger:hover{background:rgba(248,113,113,.08)}
.btn-dl{background:var(--surface2);border:1px solid var(--border2);color:var(--muted2);padding:7px 14px;font-size:.76rem}
.btn-dl:hover{border-color:var(--accent);color:var(--accent)}
.btn-group{display:flex;align-items:center;gap:8px;flex-shrink:0}
.flist{list-style:none}
.fitem{display:flex;align-items:center;gap:14px;padding:14px 0;border-bottom:1px solid rgba(30,37,53,.8);animation:fi .25s ease}
@keyframes fi{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
.fitem:last-child{border-bottom:none}
.ftype-badge{flex-shrink:0;font-family:var(--mono);font-size:.6rem;font-weight:600;padding:3px 7px;border-radius:5px;background:var(--surface2);border:1px solid var(--border2);color:var(--muted2);letter-spacing:.05em;min-width:44px;text-align:center}
.finfo{flex:1;min-width:0}
.finfo .fn{font-size:.88rem;font-weight:500;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.finfo .fs{font-family:var(--mono);font-size:.68rem;color:var(--muted);margin-top:3px}
.rename-wrap{display:none;align-items:center;gap:8px;margin-top:6px}
.rename-wrap.active{display:flex}
.rename-input{background:var(--surface2);border:1px solid var(--accent2);color:var(--text);border-radius:7px;padding:5px 10px;font-family:var(--mono);font-size:.8rem;outline:none;width:240px;max-width:100%}
.empty{text-align:center;padding:48px 0;color:var(--muted)}
.empty-icon{width:56px;height:56px;margin:0 auto 14px;background:var(--surface2);border:1px solid var(--border);border-radius:14px;display:flex;align-items:center;justify-content:center}
.empty-icon svg{width:26px;height:26px;color:var(--muted)}
.empty p{font-size:.88rem}
@media(max-width:560px){
  .phone-banner{flex-direction:column;align-items:flex-start;gap:16px}
  .phone-url{font-size:.85rem}
  h1{font-size:1.35rem}
  .btn-group{flex-wrap:wrap}
  .rename-input{width:160px}
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo-mark">
      <svg viewBox="0 0 24 24" fill="none" stroke="#0a0d14" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
        <polyline points="13 2 13 9 20 9"/>
        <line x1="9" y1="15" x2="15" y2="15"/>
        <line x1="12" y1="12" x2="12" y2="18"/>
      </svg>
    </div>
    <div class="logo-text">
      <h1>HULK SEND</h1>
      <div class="sub">Local Network Transfer / v2</div>
    </div>
  </header>

  <div id="flash-area">FLASH_PLACEHOLDER</div>

  <div class="phone-banner">
    <div class="qr-wrap">QR_PLACEHOLDER</div>
    <div class="phone-info">
      <div class="label">Mobile Access</div>
      <div class="phone-url">URL_PLACEHOLDER</div>
      <div class="phone-steps">
        <span class="step-num">1</span> Same Wi-Fi network required<br/>
        <span class="step-num">2</span> Scan QR code <b>or</b> type the address<br/>
        <span class="step-num">3</span> Upload and download from any device
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
      Upload Files
    </div>
    <div class="dropzone" id="dz">
      <input type="file" name="file" id="fi" multiple onchange="showNames(this)"/>
      <div class="dz-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
      </div>
      <div class="dz-title">Drop files here or click to browse</div>
      <div class="dz-sub">Supports multiple files at once</div>
      <div id="file-names">No files selected</div>
    </div>
    <div id="prog-label"></div>
    <div id="prog-wrap"><div id="prog-bar"></div></div>
    <button class="btn btn-primary" onclick="doUpload()">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
      Upload & Share
    </button>
  </div>

  <div class="card">
    <div class="card-title">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      Shared Files
      <span class="count-badge" id="file-count">COUNT_PLACEHOLDER</span>
    </div>
    <div id="file-list-area">LIST_PLACEHOLDER</div>
  </div>
</div>

<script>
function showNames(input) {
  const el = document.getElementById('file-names');
  if (!input.files.length) { el.textContent = 'No files selected'; return; }
  el.textContent = input.files.length === 1 ? input.files[0].name : input.files.length + ' files selected';
}
const dz = document.getElementById('dz');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
dz.addEventListener('dragleave', () => dz.classList.remove('over'));
dz.addEventListener('drop', e => {
  e.preventDefault(); dz.classList.remove('over');
  const fi = document.getElementById('fi');
  if (e.dataTransfer.files.length) { fi.files = e.dataTransfer.files; showNames(fi); }
});
function showFlash(msg, type) {
  const el = document.getElementById('flash-area');
  el.innerHTML = '<div class="flash ' + type + '"><span class="flash-dot"></span>' + msg + '</div>';
  if (type === 'ok') setTimeout(() => { el.innerHTML = ''; }, 5000);
}
function refreshList() {
  fetch('/files')
    .then(r => r.text())
    .then(h => {
      const parser = new DOMParser();
      const doc = parser.parseFromString(h, 'text/html');
      document.getElementById('file-list-area').innerHTML = doc.getElementById('file-list-area').innerHTML;
      const badge = doc.getElementById('file-count');
      if (badge) document.getElementById('file-count').textContent = badge.textContent;
    })
    .catch(() => {});
}
function doUpload() {
  const fi = document.getElementById('fi');
  if (!fi.files.length) { showFlash('Please select at least one file.', 'err'); return; }
  const formData = new FormData();
  for (const f of fi.files) formData.append('file', f);
  const bar = document.getElementById('prog-bar');
  const wrap = document.getElementById('prog-wrap');
  const label = document.getElementById('prog-label');
  wrap.style.display = 'block';
  label.style.display = 'block';
  label.textContent = 'Uploading...';
  bar.style.width = '0%';
  const xhr = new XMLHttpRequest();
  xhr.upload.addEventListener('progress', e => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded / e.total * 100);
      bar.style.width = pct + '%';
      label.textContent = 'Uploading... ' + pct + '%';
    }
  });
  xhr.addEventListener('load', () => {
    wrap.style.display = 'none';
    label.style.display = 'none';
    bar.style.width = '0%';
    try {
      const d = JSON.parse(xhr.responseText);
      if (d.ok) {
        showFlash('<strong>' + d.message + '</strong>', 'ok');
        fi.value = '';
        document.getElementById('file-names').textContent = 'No files selected';
        refreshList();
      } else {
        showFlash(d.error || 'Upload failed.', 'err');
      }
    } catch(e) {
      showFlash('Unexpected server response.', 'err');
    }
  });
  xhr.addEventListener('error', () => {
    wrap.style.display = 'none'; label.style.display = 'none';
    showFlash('Network error during upload.', 'err');
  });
  xhr.open('POST', '/upload');
  xhr.send(formData);
}
function startRename(btn, oldName) {
  const item = btn.closest('.fitem');
  const fnEl = item.querySelector('.fn');
  const rwEl = item.querySelector('.rename-wrap');
  const inp = rwEl.querySelector('.rename-input');
  inp.value = oldName;
  rwEl.classList.add('active');
  fnEl.style.display = 'none';
  inp.focus(); inp.select();
}
function cancelRename(btn) {
  const item = btn.closest('.fitem');
  item.querySelector('.fn').style.display = '';
  item.querySelector('.rename-wrap').classList.remove('active');
}
function submitRename(btn, oldName) {
  const item = btn.closest('.fitem');
  const newName = item.querySelector('.rename-input').value.trim();
  if (!newName || newName === oldName) { cancelRename(btn); return; }
  fetch('/rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ old: oldName, new: newName })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) refreshList();
    else showFlash('Rename failed: ' + (d.error || 'unknown'), 'err');
  })
  .catch(() => showFlash('Rename request failed.', 'err'));
}
function deleteFile(name) {
  if (!confirm('Delete "' + name + '"?')) return;
  fetch('/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name: name })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) refreshList();
    else showFlash('Delete failed: ' + (d.error || 'unknown'), 'err');
  })
  .catch(() => showFlash('Delete request failed.', 'err'));
}
</script>
</body>
</html>"""


def render_page(flash: str = "") -> bytes:
    fl_html, count = render_file_list_html()
    phone_url = f"http://{LOCAL_IP}:{ACTIVE_PORT}"
    page = HTML_TEMPLATE
    page = page.replace("FLASH_PLACEHOLDER", flash)
    page = page.replace("QR_PLACEHOLDER", _qr_svg(phone_url, size=160))
    page = page.replace("URL_PLACEHOLDER", html.escape(phone_url))
    page = page.replace("COUNT_PLACEHOLDER", str(count))
    page = page.replace("LIST_PLACEHOLDER", fl_html)
    return page.encode("utf-8")


def render_partial_files() -> bytes:
    fl_html, count = render_file_list_html()
    return (
        f'<div id="file-list-area">{fl_html}</div>'
        f'<span id="file-count">{count}</span>'
    ).encode("utf-8")


class FileShareHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f" [{self.address_string()}] {fmt % args}")

    def _send_html(self, body: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _404(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(render_page())
        elif path == "/files":
            self._send_html(render_partial_files())
        elif path.startswith("/download/"):
            fname = urllib.parse.unquote(path[len("/download/"):])
            filepath = SHARE_DIR / Path(fname).name
            if not filepath.is_file():
                self._404()
                return
            mime = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
            size = filepath.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            self._404()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/upload":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                fields = parse_multipart(self.headers, body)
                saved = []
                for name, filename, data in fields:
                    if name == "file" and filename and data:
                        safe_name = Path(filename).name
                        (SHARE_DIR / safe_name).write_bytes(data)
                        saved.append(html.escape(safe_name) + f" ({human_size(len(data))})")
                if saved:
                    self._send_json({"ok": True, "message": "Uploaded: " + ", ".join(saved)})
                else:
                    self._send_json({"ok": False, "error": "No valid file found"}, 400)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path == "/delete":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length))
                name = Path(data.get("name", "")).name
                fp = SHARE_DIR / name
                if fp.is_file():
                    fp.unlink()
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False, "error": "File not found"}, 404)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path == "/rename":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length))
                old = Path(data.get("old", "")).name
                new = Path(data.get("new", "")).name
                old_path = SHARE_DIR / old
                new_path = SHARE_DIR / new
                if not old_path.is_file():
                    self._send_json({"ok": False, "error": "Original file not found"}, 404)
                elif new_path.exists():
                    self._send_json({"ok": False, "error": "Target name already exists"}, 409)
                else:
                    old_path.rename(new_path)
                    self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
        else:
            self._404()


# ── Main ──────────────────────────────────────────────────────────────────────
ACTIVE_PORT = PREFERRED_PORT
LOCAL_IP = "127.0.0.1"


def main():
    global ACTIVE_PORT, LOCAL_IP
    ACTIVE_PORT = find_free_port()
    LOCAL_IP = get_local_ip()

    if ACTIVE_PORT != PREFERRED_PORT:
        print(f"Port {PREFERRED_PORT} in use → using {ACTIVE_PORT}")

    server = http.server.HTTPServer(("0.0.0.0", ACTIVE_PORT), FileShareHandler)

    pc_url    = f"http://localhost:{ACTIVE_PORT}"
    phone_url = f"http://{LOCAL_IP}:{ACTIVE_PORT}"

    print("\n" + "="*56)
    print(" FileBeam v2 – Local File Share")
    print("="*56)
    print(f"  PC:        {pc_url}")
    print(f"  Phone:     {phone_url}  ← open this one")
    print(f"  Folder:    {SHARE_DIR.resolve()}")
    print("  Stop:      Ctrl+C")
    print("="*56 + "\n")

    threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(pc_url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.\n")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()