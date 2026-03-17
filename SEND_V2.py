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
import os
import tempfile
import hashlib
import secrets
import ssl
import subprocess
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PREFERRED_PORT    = 8080
HTTPS_PORT        = 8443
SHARE_DIR         = Path("./HULK")
SHARE_DIR.mkdir(exist_ok=True)
CHUNK_SIZE        = 8 * 1024 * 1024   # 8 MB streaming chunks

# ── Authentication ─────────────────────────────────────────────────────────────
# Change these or pass via env: HULK_USER / HULK_PASS
AUTH_USER     = os.environ.get("HULK_USER", "hulk")
AUTH_PASS     = os.environ.get("HULK_PASS", "smash")
AUTH_ENABLED  = os.environ.get("HULK_AUTH", "1") != "0"

_sessions: set[str] = set()
SESSION_COOKIE = "hulk_sess"

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

PASS_HASH = _hash(AUTH_PASS)

def new_session() -> str:
    tok = secrets.token_hex(32)
    _sessions.add(tok)
    return tok

def valid_session(cookie_header: str) -> bool:
    if not AUTH_ENABLED:
        return True
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() == SESSION_COOKIE and v.strip() in _sessions:
            return True
    return False

# ── HTTPS / self-signed cert ───────────────────────────────────────────────────
CERT_FILE = Path("hulk_cert.pem")
KEY_FILE  = Path("hulk_key.pem")

def ensure_cert():
    if CERT_FILE.exists() and KEY_FILE.exists():
        return True
    try:
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(KEY_FILE), "-out", str(CERT_FILE),
            "-days", "365", "-nodes",
            "-subj", "/CN=hulk-local"
        ], check=True, capture_output=True)
        return True
    except Exception as e:
        print(f"[HTTPS] openssl not available: {e} — HTTP only")
        return False

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
    raise OSError(f"No free port in {start}-{start+19}")

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def file_type_label(name: str) -> str:
    ext = Path(name).suffix.lower()
    groups = {
        "PDF":   [".pdf"],
        "Word":  [".doc", ".docx"],
        "Text":  [".txt", ".md", ".log"],
        "ZIP":   [".zip", ".tar", ".gz", ".rar", ".7z"],
        "Image": [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif"],
        "Video": [".mp4", ".mov", ".avi", ".mkv", ".webm"],
        "Audio": [".mp3", ".wav", ".flac", ".ogg", ".m4a"],
        "Code":  [".py", ".js", ".ts", ".html", ".css", ".json", ".sh", ".bat", ".c", ".cpp", ".rs", ".go"],
        "Sheet": [".xls", ".xlsx", ".csv"],
        "Slide": [".ppt", ".pptx"],
        "App":   [".exe", ".apk", ".dmg"],
    }
    for label, exts in groups.items():
        if ext in exts:
            return label
    return ext.lstrip(".").upper() or "File"

def is_previewable_image(name: str) -> bool:
    return Path(name).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg")

def is_previewable_video(name: str) -> bool:
    return Path(name).suffix.lower() in (".mp4", ".webm", ".mov")

# ── Streaming multipart parser ─────────────────────────────────────────────────
def stream_multipart_to_disk(rfile, content_type: str, content_length: int, dest_dir: Path) -> list[tuple[str, int]]:
    m = re.search(r'boundary=([^\s;]+)', content_type)
    if not m:
        raise ValueError("No boundary in Content-Type")

    boundary       = m.group(1).encode()
    dash_boundary  = b"--" + boundary
    final_boundary = b"--" + boundary + b"--"
    saved          = []
    buf            = b""
    _consumed      = [0]

    def read_more(n=CHUNK_SIZE):
        nonlocal buf
        remaining = content_length - _consumed[0]
        if remaining <= 0:
            return
        chunk = rfile.read(min(n, remaining))
        _consumed[0] += len(chunk)
        buf += chunk

    def consume(n):
        nonlocal buf
        buf = buf[n:]

    def find_line():
        while True:
            idx = buf.find(b"\r\n")
            if idx != -1:
                line = buf[:idx]
                consume(idx + 2)
                return line
            if _consumed[0] >= content_length:
                line = buf; consume(len(buf)); return line
            read_more()

    read_more()

    while True:
        while True:
            line = find_line()
            if line == dash_boundary or line == final_boundary:
                break
            if not buf and _consumed[0] >= content_length:
                return saved
        if line == final_boundary:
            break

        part_headers = {}
        while True:
            hline = find_line()
            if hline == b"":
                break
            if b":" in hline:
                k, v = hline.split(b":", 1)
                part_headers[k.strip().lower().decode()] = v.strip().decode()

        disp    = part_headers.get("content-disposition", "")
        fname_m = re.search(r'filename="([^"]*)"', disp)
        if not fname_m:
            continue

        # Support webkitRelativePath (folder upload) — preserve sub-path inside HULK
        rel_path_m = re.search(r'name="([^"]*)"', disp)
        raw_name   = fname_m.group(1)
        filename   = Path(raw_name).name
        if not filename:
            continue

        # Field name may carry relative path for folder uploads
        field_name = rel_path_m.group(1) if rel_path_m else ""
        sub_dir    = dest_dir
        if "/" in field_name:
            # folder/sub/file.txt → create sub dirs
            parts = Path(field_name).parts[:-1]
            sub_dir = dest_dir.joinpath(*parts)
            sub_dir.mkdir(parents=True, exist_ok=True)
        # Also handle filename containing path separator (some browsers)
        if "/" in raw_name or "\\" in raw_name:
            parts = Path(raw_name.replace("\\", "/")).parts
            if len(parts) > 1:
                sub_dir = dest_dir.joinpath(*parts[:-1])
                sub_dir.mkdir(parents=True, exist_ok=True)

        dest_path   = sub_dir / filename
        total_written = 0
        tmp_fd, tmp_path = tempfile.mkstemp(dir=sub_dir, prefix=".upload_")
        try:
            with os.fdopen(tmp_fd, "wb") as out:
                next_boundary = b"\r\n" + dash_boundary
                leftover = b""
                while True:
                    while len(buf) < len(next_boundary) + 8 and _consumed[0] < content_length:
                        read_more()
                    search = leftover + buf
                    idx    = search.find(next_boundary)
                    if idx != -1:
                        out.write(search[:idx])
                        total_written += idx
                        consume(max(0, idx - len(leftover) + len(next_boundary)))
                        leftover = b""
                        break
                    else:
                        safe_len = max(0, len(search) - (len(next_boundary) - 1))
                        if safe_len > 0:
                            out.write(search[:safe_len])
                            total_written += safe_len
                            consume(max(0, safe_len - len(leftover)))
                            leftover = search[safe_len:]
                        elif _consumed[0] >= content_length:
                            out.write(search)
                            total_written += len(search)
                            leftover = b""
                            break
                        else:
                            leftover = search
                            buf = b""
                            read_more()
        except Exception:
            os.unlink(tmp_path)
            raise

        os.replace(tmp_path, dest_path)
        # Store relative path for display
        try:
            rel = dest_path.relative_to(dest_dir)
        except ValueError:
            rel = Path(filename)
        saved.append((str(rel), total_written))

    return saved

# ── QR Code ───────────────────────────────────────────────────────────────────
def _qr_svg(url: str, size: int = 180) -> str:
    """Generate a QR code SVG. Tries segno first, falls back to pure-Python QR."""
    # ── Try segno (if installed) ───────────────────────────────────────────────
    try:
        import segno as _segno, io as _io
        qr  = _segno.make(url, error='h')
        buf = _io.BytesIO()
        qr.save(buf, kind='svg', scale=4.8, border=0, dark='black', light='white', xmldecl=False)
        svg = buf.getvalue().decode('utf-8')
        return svg.replace("<svg", f'<svg width="{size}" height="{size}"', 1)
    except Exception:
        pass

    # ── Pure-Python QR (no dependencies) ──────────────────────────────────────
    try:
        return _qr_svg_pure(url, size)
    except Exception:
        pass

    # ── Last-resort: text fallback ─────────────────────────────────────────────
    safe_url = html.escape(url)
    return (
        f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="100%" height="100%" fill="#0f1117" rx="10"/>'
        f'<text x="50%" y="44%" text-anchor="middle" fill="#5eead4" '
        f'font-family="monospace" font-size="11" font-weight="bold">Type this address:</text>'
        f'<text x="50%" y="62%" text-anchor="middle" fill="#fff" '
        f'font-family="monospace" font-size="9">{safe_url}</text>'
        f'</svg>'
    )


# ── Pure-Python QR Code (Version 1-10, ECC=M) ─────────────────────────────────
# Implements enough of the QR spec to encode short URLs reliably.

def _qr_svg_pure(data: str, size: int = 180) -> str:
    """Render a QR code as an SVG string without any third-party libraries."""
    matrix = _qr_matrix(data)
    n      = len(matrix)
    cell   = size / (n + 8)          # add 4-module quiet zone each side
    offset = cell * 4
    total  = size

    rects = []
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                x = offset + c * cell
                y = offset + r * cell
                rects.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell:.2f}" height="{cell:.2f}"/>')

    inner = "\n".join(rects)
    return (
        f'<svg width="{total}" height="{total}" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {total} {total}">'
        f'<rect width="{total}" height="{total}" fill="white"/>'
        f'<g fill="black">{inner}</g>'
        f'</svg>'
    )


def _qr_matrix(text: str):
    """Return a 2-D boolean matrix for the QR code of *text* (byte mode, ECC=M)."""
    import struct

    # ── Reed-Solomon GF(256) ──────────────────────────────────────────────────
    EXP = [0] * 512
    LOG = [0] * 256
    x = 1
    for i in range(255):
        EXP[i] = x
        LOG[x]  = i
        x = x << 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        EXP[i] = EXP[i - 255]

    def gf_mul(a, b):
        if a == 0 or b == 0:
            return 0
        return EXP[LOG[a] + LOG[b]]

    def rs_poly_mul(p, q):
        r = [0] * (len(p) + len(q) - 1)
        for i, a in enumerate(p):
            for j, b in enumerate(q):
                r[i + j] ^= gf_mul(a, b)
        return r

    def rs_generator(n):
        g = [1]
        for i in range(n):
            g = rs_poly_mul(g, [1, EXP[i]])
        return g

    def rs_remainder(data, gen):
        d = list(data) + [0] * (len(gen) - 1)
        for i in range(len(data)):
            if d[i]:
                coef = d[i]
                for j, g in enumerate(gen):
                    d[i + j] ^= gf_mul(coef, g)
        return d[len(data):]

    # ── Version / capacity selection ──────────────────────────────────────────
    # ECC=M capacities (bytes) for versions 1-10
    CAP = [0,16,28,44,64,86,108,124,154,182,216]
    data_bytes = text.encode('iso-8859-1', errors='replace')
    n_data = len(data_bytes)
    version = None
    for v in range(1, 11):
        if n_data <= CAP[v]:
            version = v
            break
    if version is None:
        version = 10   # truncate silently

    # ECC codewords per block for ECC=M, versions 1-10
    ECC_PER = [0,10,16,26,18,24,16,18,22,22,26]
    # Data codewords for ECC=M, versions 1-10
    DATA_CW  = [0,16,28,44,64,86,108,124,154,182,216]
    total_cw = DATA_CW[version]
    ecc_cw   = ECC_PER[version]
    data_cw  = total_cw - ecc_cw

    # ── Build data bitstream ──────────────────────────────────────────────────
    bits = []

    def push(val, length):
        for i in range(length - 1, -1, -1):
            bits.append((val >> i) & 1)

    push(0b0100, 4)                  # byte mode indicator
    push(min(n_data, data_cw - 2), 8)  # character count (rough; capped)
    for b in data_bytes[:data_cw - 2]:
        push(b, 8)

    # Terminator + padding
    for _ in range(4):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)

    codewords = [int(''.join(str(b) for b in bits[i:i+8]), 2)
                 for i in range(0, min(len(bits), data_cw * 8), 8)]

    pad_bytes = [0xEC, 0x11]
    while len(codewords) < data_cw:
        codewords.append(pad_bytes[len(codewords) % 2])

    # ── Reed-Solomon ──────────────────────────────────────────────────────────
    gen = rs_generator(ecc_cw)
    ecc = rs_remainder(codewords, gen)
    all_cw = codewords + ecc

    # ── Final bitstream ───────────────────────────────────────────────────────
    final_bits = []
    for cw in all_cw:
        for i in range(7, -1, -1):
            final_bits.append((cw >> i) & 1)
    # Remainder bits
    rem = [0, 7, 7, 7, 7, 7, 0, 0, 0, 0][version - 1]
    final_bits += [0] * rem

    # ── Build matrix ──────────────────────────────────────────────────────────
    size_m = version * 4 + 17
    mat    = [[0] * size_m for _ in range(size_m)]
    func   = [[False] * size_m for _ in range(size_m)]  # functional modules

    def set_func(r, c, v):
        if 0 <= r < size_m and 0 <= c < size_m:
            mat[r][c]  = v
            func[r][c] = True

    # Finder pattern
    def finder(tr, tc):
        for r in range(7):
            for c in range(7):
                v = 1 if (r in (0,6) or c in (0,6) or (2<=r<=4 and 2<=c<=4)) else 0
                set_func(tr+r, tc+c, v)
        # Separators
        for i in range(8):
            set_func(tr+7, tc+i, 0)
            set_func(tr+i, tc+7, 0)

    finder(0, 0)
    finder(0, size_m - 7)
    finder(size_m - 7, 0)

    # Timing patterns
    for i in range(8, size_m - 8):
        v = 1 if i % 2 == 0 else 0
        set_func(6, i, v)
        set_func(i, 6, v)

    # Dark module
    set_func(size_m - 8, 8, 1)

    # Format info placeholders (mark as functional, fill later)
    for i in range(9):
        func[8][i] = True
        func[i][8] = True
    for i in range(size_m - 8, size_m):
        func[8][i] = True
        func[i][8] = True

    # Alignment patterns (version >= 2)
    ALIGN_POS = {
        1: [], 2: [6,18], 3: [6,22], 4: [6,26], 5: [6,30],
        6: [6,34], 7: [6,22,38], 8: [6,24,42], 9: [6,26,46], 10: [6,28,50]
    }
    apos = ALIGN_POS.get(version, [])
    for ar in apos:
        for ac in apos:
            if func[ar][ac]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    v = 1 if (abs(dr)==2 or abs(dc)==2 or (dr==0 and dc==0)) else 0
                    set_func(ar+dr, ac+dc, v)

    # ── Place data bits ───────────────────────────────────────────────────────
    bit_idx = 0
    col = size_m - 1
    going_up = True
    while col >= 0:
        if col == 6:
            col -= 1
        for row_off in range(size_m):
            row = (size_m - 1 - row_off) if going_up else row_off
            for dc in range(2):
                c = col - dc
                if not func[row][c]:
                    if bit_idx < len(final_bits):
                        mat[row][c] = final_bits[bit_idx]
                    bit_idx += 1
        going_up = not going_up
        col -= 2

    # ── Apply mask pattern 0 (i+j) % 2 == 0 ─────────────────────────────────
    for r in range(size_m):
        for c in range(size_m):
            if not func[r][c] and (r + c) % 2 == 0:
                mat[r][c] ^= 1

    # ── Write format information (ECC=M, mask=0) ─────────────────────────────
    # Pre-computed format string for ECC=M (01), mask 0 (000): 101010000010010
    # XORed with mask 101010000010010
    fmt = 0b101010000010010  # ECC=M, mask 0
    fmt_bits = [(fmt >> (14 - i)) & 1 for i in range(15)]

    positions = [(8,0),(8,1),(8,2),(8,3),(8,4),(8,5),(8,7),(8,8),
                 (7,8),(5,8),(4,8),(3,8),(2,8),(1,8),(0,8)]
    for i, (r, c) in enumerate(positions):
        mat[r][c] = fmt_bits[i]
    # Bottom-left
    for i in range(7):
        mat[size_m - 1 - i][8] = fmt_bits[i]
    mat[size_m - 8][8] = 1   # dark module
    # Top-right
    for i in range(8):
        mat[8][size_m - 8 + i] = fmt_bits[7 + i]

    return mat

# ── File list HTML ────────────────────────────────────────────────────────────
def render_file_list_html() -> tuple[str, int]:
    try:
        entries = sorted(
            (f for f in SHARE_DIR.rglob("*") if f.is_file()),
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
        try:
            rel = f.relative_to(SHARE_DIR)
        except ValueError:
            rel = Path(f.name)
        enc   = urllib.parse.quote(str(rel))
        safe  = html.escape(str(rel))
        jsafe = safe.replace("'", "\\'")
        ftype = file_type_label(f.name)
        size_str = human_size(f.stat().st_size)

        preview_btn = ""
        if is_previewable_image(f.name):
            preview_btn = f'<button class="btn btn-ghost" onclick="previewMedia(\'{enc}\',\'image\')">Preview</button>'
        elif is_previewable_video(f.name):
            preview_btn = f'<button class="btn btn-ghost" onclick="previewMedia(\'{enc}\',\'video\')">Preview</button>'

        # show folder path prefix if nested
        display_name = safe
        folder_badge = ""
        parts = list(rel.parts)
        if len(parts) > 1:
            folder_path = html.escape("/".join(parts[:-1]))
            folder_badge = f'<span class="folder-badge">📁 {folder_path}</span>'
            display_name = html.escape(parts[-1])

        rows.append(
            f'<li class="fitem">'
            f'<span class="ftype-badge">{html.escape(ftype)}</span>'
            f'<div class="finfo">'
            f'{folder_badge}'
            f'<div class="fn" title="{safe}">{display_name}</div>'
            f'<div class="fs">{size_str}</div>'
            f'<div class="rename-wrap">'
            f'<input class="rename-input" type="text" value="{html.escape(f.name)}"/>'
            f'<button class="btn btn-ghost" onclick="submitRename(this, \'{jsafe}\')">Save</button>'
            f'<button class="btn btn-ghost" onclick="cancelRename(this)">Cancel</button>'
            f'</div>'
            f'</div>'
            f'<div class="btn-group">'
            f'<a class="btn btn-dl" href="/download/{enc}" download>Download</a>'
            f'{preview_btn}'
            f'<button class="btn btn-ghost" onclick="startRename(this, \'{jsafe}\')">Rename</button>'
            f'<button class="btn btn-danger" onclick="deleteFile(\'{jsafe}\')">Delete</button>'
            f'</div>'
            f'</li>'
        )

    return f'<ul class="flist">{"".join(rows)}</ul>', len(rows)

# ── Login page ────────────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>HULK — Login</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
:root{--bg:#080b10;--surface:#111620;--border:#1e2535;--accent:#5eead4;--accent2:#818cf8;--text:#e2e8f0;--muted:#64748b;--danger:#f87171;--mono:'IBM Plex Mono',monospace;--sans:'Instrument Sans',sans-serif;}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;display:flex;align-items:center;justify-content:center;}
body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(94,234,212,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(94,234,212,.04) 1px,transparent 1px);background-size:48px 48px;pointer-events:none}
.card{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:40px 36px;width:100%;max-width:380px;position:relative;z-index:1;}
.logo{display:flex;align-items:center;gap:12px;margin-bottom:28px;}
.logo-mark{width:40px;height:40px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:10px;display:flex;align-items:center;justify-content:center;}
.logo-mark svg{width:20px;height:20px;}
h1{font-size:1.4rem;font-weight:700;color:#fff;}
.sub{font-family:var(--mono);font-size:.6rem;color:var(--muted);letter-spacing:.1em;text-transform:uppercase;}
label{display:block;font-size:.78rem;color:var(--muted);margin-bottom:6px;margin-top:16px;}
input[type=text],input[type=password]{width:100%;background:#0d1117;border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:var(--mono);font-size:.9rem;padding:10px 14px;outline:none;transition:border .15s;}
input:focus{border-color:var(--accent);}
.btn{display:block;width:100%;margin-top:22px;padding:12px;background:var(--accent);color:#0a0d14;font-family:var(--sans);font-size:.9rem;font-weight:700;border:none;border-radius:10px;cursor:pointer;transition:opacity .15s;}
.btn:hover{opacity:.85;}
.err{color:var(--danger);font-size:.8rem;margin-top:14px;text-align:center;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="logo-mark">
      <svg viewBox="0 0 24 24" fill="none" stroke="#0a0d14" stroke-width="2.5"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
    </div>
    <div>
      <h1>HULK SEND</h1>
      <div class="sub">Local File Transfer</div>
    </div>
  </div>
  ERR_PLACEHOLDER
  <form method="POST" action="/login">
    <label>Username</label>
    <input type="text" name="username" autocomplete="username" autofocus/>
    <label>Password</label>
    <input type="password" name="password" autocomplete="current-password"/>
    <button class="btn" type="submit">Sign In</button>
  </form>
</div>
</body>
</html>"""

# ── Main HTML Template ────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>HULK</title>
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
header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:40px}
.header-left{display:flex;align-items:center;gap:16px;}
.logo-mark{width:44px;height:44px;flex-shrink:0;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:12px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 32px rgba(94,234,212,.25)}
.logo-mark svg{width:22px;height:22px}
.logo-text h1{font-size:1.6rem;font-weight:700;letter-spacing:-.03em;color:#fff}
.logo-text .sub{font-family:var(--mono);font-size:.65rem;color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-top:2px}
.logout-btn{background:transparent;border:1px solid var(--border2);color:var(--muted2);font-family:var(--sans);font-size:.76rem;font-weight:600;padding:7px 16px;border-radius:8px;cursor:pointer;transition:all .15s;}
.logout-btn:hover{border-color:var(--danger);color:var(--danger);}
.https-badge{font-family:var(--mono);font-size:.6rem;color:var(--ok);background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.2);padding:3px 8px;border-radius:20px;letter-spacing:.08em;}
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
/* Upload tabs */
.upload-tabs{display:flex;gap:8px;margin-bottom:16px;}
.tab-btn{background:var(--surface2);border:1px solid var(--border2);color:var(--muted2);font-family:var(--sans);font-size:.78rem;font-weight:600;padding:7px 16px;border-radius:8px;cursor:pointer;transition:all .15s;}
.tab-btn.active{background:rgba(94,234,212,.1);border-color:var(--accent);color:var(--accent);}
.tab-panel{display:none;} .tab-panel.active{display:block;}
.dropzone{border:1.5px dashed var(--border2);border-radius:14px;padding:40px 24px;text-align:center;cursor:pointer;transition:all .2s;position:relative;margin-bottom:16px}
.dropzone:hover,.dropzone.over{border-color:var(--accent);background:rgba(94,234,212,.04)}
.dropzone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.dz-icon{width:48px;height:48px;margin:0 auto 12px;background:var(--surface2);border:1px solid var(--border2);border-radius:12px;display:flex;align-items:center;justify-content:center}
.dz-icon svg{width:22px;height:22px;color:var(--accent)}
.dz-title{font-size:.95rem;font-weight:600;color:var(--text);margin-bottom:5px}
.dz-sub{font-size:.8rem;color:var(--muted)}
#file-names,#folder-names{font-family:var(--mono);font-size:.73rem;color:var(--accent2);margin-top:10px;min-height:18px;text-align:center}
/* Upload queue */
#upload-queue{margin-bottom:14px;}
.queue-item{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;margin-bottom:6px;font-size:.8rem;}
.qi-name{flex:1;font-family:var(--mono);color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.qi-size{color:var(--muted);font-family:var(--mono);font-size:.7rem;white-space:nowrap;}
.qi-status{font-family:var(--mono);font-size:.7rem;white-space:nowrap;}
.qi-status.pending{color:var(--muted);}
.qi-status.uploading{color:var(--accent);}
.qi-status.done{color:var(--ok);}
.qi-status.paused{color:#fb923c;}
.qi-status.err{color:var(--danger);}
.qi-bar-wrap{width:60px;height:4px;background:var(--border);border-radius:2px;overflow:hidden;flex-shrink:0;}
.qi-bar{height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .15s;}
.qi-remove{background:none;border:none;color:var(--muted);cursor:pointer;font-size:.9rem;padding:0 4px;transition:color .15s;}
.qi-remove:hover{color:var(--danger);}
/* Global progress */
#prog-wrap{display:none;margin-bottom:14px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;overflow:hidden;height:8px}
#prog-bar{height:100%;width:0%;transition:width .15s;background:linear-gradient(90deg,var(--accent),var(--accent2))}
#prog-label{font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-bottom:8px;display:none;text-align:right}
/* Upload controls */
.upload-controls{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;}
.btn{display:inline-flex;align-items:center;gap:8px;font-family:var(--sans);font-size:.875rem;font-weight:600;border:none;border-radius:10px;cursor:pointer;transition:all .15s;text-decoration:none}
.btn-primary{background:var(--accent);color:#0a0d14;padding:11px 26px;box-shadow:0 4px 20px rgba(94,234,212,.25)}
.btn-primary:hover{opacity:.88;transform:translateY(-1px);box-shadow:0 6px 28px rgba(94,234,212,.35)}
.btn-primary:active{transform:none}
.btn-primary:disabled{opacity:.4;cursor:not-allowed;transform:none;}
.btn-ghost{background:transparent;border:1px solid var(--border2);color:var(--muted2);padding:7px 14px;font-size:.76rem}
.btn-ghost:hover{border-color:var(--accent2);color:var(--accent2)}
.btn-warn{background:transparent;border:1px solid rgba(251,146,60,.3);color:#fb923c;padding:7px 14px;font-size:.76rem}
.btn-warn:hover{background:rgba(251,146,60,.08);}
.btn-danger{background:transparent;border:1px solid rgba(248,113,113,.25);color:var(--danger);padding:7px 14px;font-size:.76rem}
.btn-danger:hover{background:rgba(248,113,113,.08)}
.btn-dl{background:var(--surface2);border:1px solid var(--border2);color:var(--muted2);padding:7px 14px;font-size:.76rem}
.btn-dl:hover{border-color:var(--accent);color:var(--accent)}
/* File list */
.flist{list-style:none;display:flex;flex-direction:column;gap:10px}
.fitem{display:flex;align-items:center;gap:14px;background:var(--surface2);border:1px solid var(--border);border-radius:14px;padding:14px 16px;transition:border-color .15s;flex-wrap:wrap}
.fitem:hover{border-color:var(--border2)}
.ftype-badge{font-family:var(--mono);font-size:.6rem;font-weight:600;background:rgba(94,234,212,.08);border:1px solid rgba(94,234,212,.15);color:var(--accent);padding:3px 8px;border-radius:6px;flex-shrink:0;letter-spacing:.05em;text-transform:uppercase}
.finfo{flex:1;min-width:0}
.folder-badge{font-family:var(--mono);font-size:.6rem;color:var(--accent2);display:block;margin-bottom:2px;}
.fn{font-size:.9rem;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs{font-family:var(--mono);font-size:.7rem;color:var(--muted);margin-top:2px}
.rename-wrap{display:none;align-items:center;gap:8px;margin-top:6px}
.rename-wrap.active{display:flex}
.rename-input{flex:1;background:var(--bg2);border:1px solid var(--border2);color:var(--text);font-family:var(--mono);font-size:.8rem;padding:6px 10px;border-radius:6px;outline:none}
.rename-input:focus{border-color:var(--accent)}
.btn-group{display:flex;gap:7px;flex-wrap:wrap}
.empty{text-align:center;padding:48px 24px;color:var(--muted)}
.empty-icon{width:56px;height:56px;margin:0 auto 16px;background:var(--surface2);border:1px solid var(--border);border-radius:14px;display:flex;align-items:center;justify-content:center}
.empty-icon svg{width:26px;height:26px}
/* Preview modal */
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:100;align-items:center;justify-content:center;}
.modal-backdrop.open{display:flex;}
.modal{background:var(--surface);border:1px solid var(--border2);border-radius:20px;max-width:90vw;max-height:90vh;overflow:auto;padding:20px;position:relative;}
.modal-close{position:absolute;top:12px;right:14px;background:none;border:none;color:var(--muted2);font-size:1.4rem;cursor:pointer;line-height:1;}
.modal-close:hover{color:var(--text);}
.modal img{max-width:80vw;max-height:75vh;border-radius:10px;display:block;}
.modal video{max-width:80vw;max-height:75vh;border-radius:10px;display:block;}
@media(max-width:600px){
  .fitem{flex-direction:column;align-items:flex-start}
  .btn-group{width:100%}
  .upload-controls{flex-direction:column;}
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="header-left">
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
        <div class="sub">Local Network Transfer</div>
      </div>
      HTTPS_BADGE_PLACEHOLDER
    </div>
    AUTH_LOGOUT_PLACEHOLDER
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
        <span class="step-num">3</span> Login then upload &amp; download from any device<br/>
        <span class="step-num">4</span> <b>No file size limit</b> — streams directly to disk<br/>
        <span class="step-num">5</span> Pause/resume large uploads anytime
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
      Upload Files
    </div>

    <!-- Upload mode tabs -->
    <div class="upload-tabs">
      <button class="tab-btn active" onclick="switchTab('files',this)">📄 Files</button>
      <button class="tab-btn" onclick="switchTab('folder',this)">📁 Folder</button>
      <button class="tab-btn" onclick="switchTab('drop',this)">🗂 Drop Zone</button>
    </div>

    <!-- Files tab -->
    <div class="tab-panel active" id="tab-files">
      <div class="dropzone" id="dz-files">
        <input type="file" id="fi" multiple onchange="addFilesToQueue(this.files)"/>
        <div class="dz-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg></div>
        <div class="dz-title">Drop files here or click to browse</div>
        <div class="dz-sub">Select multiple files — they queue up below</div>
        <div id="file-names">No files selected</div>
      </div>
    </div>

    <!-- Folder tab -->
    <div class="tab-panel" id="tab-folder">
      <div class="dropzone" id="dz-folder">
        <input type="file" id="fi-folder" webkitdirectory multiple onchange="addFilesToQueue(this.files, true)"/>
        <div class="dz-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></div>
        <div class="dz-title">Click to select a folder</div>
        <div class="dz-sub">Uploads entire folder tree preserving structure</div>
        <div id="folder-names">No folder selected</div>
      </div>
    </div>

    <!-- Drop Zone tab (drag folders) -->
    <div class="tab-panel" id="tab-drop">
      <div class="dropzone" id="dz-drop" style="min-height:120px;">
        <div class="dz-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg></div>
        <div class="dz-title">Drag &amp; drop files or folders here</div>
        <div class="dz-sub">Supports multiple files and entire folder trees</div>
      </div>
    </div>

    <!-- Queue -->
    <div id="upload-queue"></div>

    <div id="prog-label"></div>
    <div id="prog-wrap"><div id="prog-bar"></div></div>

    <div class="upload-controls">
      <button class="btn btn-primary" id="btn-upload" onclick="startUploadQueue()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
        Upload All
      </button>
      <button class="btn btn-warn" id="btn-pause" onclick="togglePause()" style="display:none;">
        ⏸ Pause
      </button>
      <button class="btn btn-ghost" onclick="clearQueue()">Clear Queue</button>
    </div>
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

<!-- Preview modal -->
<div class="modal-backdrop" id="preview-modal" onclick="closePreview(event)">
  <div class="modal" id="preview-content">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div id="preview-body"></div>
  </div>
</div>

<script>
// ── Tab switching ──────────────────────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

// ── Upload queue system ────────────────────────────────────────────────────────
let queue = [];     // [{file, name, relPath, status, progress, xhr}]
let uploading = false;
let paused    = false;
let currentIdx = -1;

function queueId(i) { return 'qi-' + i; }

function addFilesToQueue(files, isFolder) {
  for (const f of files) {
    const relPath = f.webkitRelativePath || f.name;
    queue.push({ file: f, name: f.name, relPath, status: 'pending', progress: 0, xhr: null });
  }
  renderQueue();
  const el = document.getElementById(isFolder ? 'folder-names' : 'file-names');
  if (el) el.textContent = files.length === 1 ? files[0].name : files.length + ' files selected';
}

function renderQueue() {
  const el = document.getElementById('upload-queue');
  if (!queue.length) { el.innerHTML = ''; return; }
  el.innerHTML = queue.map((item, i) => {
    const pct = Math.round(item.progress);
    return `<div class="queue-item" id="${queueId(i)}">
      <div class="qi-name" title="${escHtml(item.relPath)}">${escHtml(item.name)}</div>
      <div class="qi-size">${humanSize(item.file.size)}</div>
      <div class="qi-bar-wrap"><div class="qi-bar" id="bar-${i}" style="width:${pct}%"></div></div>
      <div class="qi-status ${item.status}" id="qs-${i}">${statusLabel(item.status, pct)}</div>
      ${item.status === 'pending' ? `<button class="qi-remove" onclick="removeFromQueue(${i})" title="Remove">✕</button>` : ''}
    </div>`;
  }).join('');
}

function statusLabel(s, pct) {
  if (s === 'pending')   return 'Pending';
  if (s === 'uploading') return pct + '%';
  if (s === 'done')      return '✓ Done';
  if (s === 'paused')    return '⏸ Paused';
  if (s === 'err')       return '✗ Error';
  return s;
}

function removeFromQueue(i) {
  queue.splice(i, 1);
  renderQueue();
}

function clearQueue() {
  queue = [];
  renderQueue();
  document.getElementById('file-names').textContent = 'No files selected';
  document.getElementById('folder-names').textContent = 'No folder selected';
}

function updateQueueItem(i, status, progress) {
  queue[i].status   = status;
  queue[i].progress = progress;
  const barEl = document.getElementById('bar-' + i);
  const stEl  = document.getElementById('qs-' + i);
  if (barEl) barEl.style.width = progress + '%';
  if (stEl)  { stEl.className = 'qi-status ' + status; stEl.textContent = statusLabel(status, Math.round(progress)); }
}

// ── Pause / Resume ─────────────────────────────────────────────────────────────
function togglePause() {
  paused = !paused;
  const btn = document.getElementById('btn-pause');
  if (paused) {
    btn.textContent = '▶ Resume';
    btn.className = 'btn btn-primary';
    if (currentIdx >= 0 && queue[currentIdx] && queue[currentIdx].xhr) {
      queue[currentIdx].xhr.abort();
      updateQueueItem(currentIdx, 'paused', queue[currentIdx].progress);
    }
  } else {
    btn.textContent = '⏸ Pause';
    btn.className = 'btn btn-warn';
    uploadNext();
  }
}

// ── Sequential uploader ────────────────────────────────────────────────────────
function startUploadQueue() {
  if (!queue.length) { showFlash('No files in queue.', 'err'); return; }
  if (uploading) return;
  uploading = true;
  paused = false;
  document.getElementById('btn-pause').style.display = '';
  document.getElementById('btn-upload').disabled = true;
  uploadNext();
}

function uploadNext() {
  if (paused) return;
  const i = queue.findIndex(q => q.status === 'pending' || q.status === 'paused');
  if (i === -1) {
    uploading = false;
    document.getElementById('btn-pause').style.display = 'none';
    document.getElementById('btn-upload').disabled = false;
    showFlash('All uploads complete!', 'ok');
    refreshList();
    return;
  }
  currentIdx = i;
  const item = queue[i];
  updateQueueItem(i, 'uploading', item.progress);
  const formData = new FormData();
  // Send relative path as field name so server can reconstruct folder tree
  formData.append(item.relPath, item.file, item.relPath);

  const xhr = new XMLHttpRequest();
  queue[i].xhr = xhr;

  xhr.upload.addEventListener('progress', e => {
    if (e.lengthComputable) {
      const pct = (e.loaded / e.total) * 100;
      updateQueueItem(i, 'uploading', pct);
    }
  });
  xhr.addEventListener('load', () => {
    try {
      const d = JSON.parse(xhr.responseText);
      if (d.ok) {
        updateQueueItem(i, 'done', 100);
      } else {
        updateQueueItem(i, 'err', 0);
        showFlash('Upload failed: ' + (d.error || 'unknown'), 'err');
      }
    } catch(e) {
      updateQueueItem(i, 'err', 0);
    }
    if (!paused) uploadNext();
  });
  xhr.addEventListener('error', () => {
    if (!paused) {
      updateQueueItem(i, 'err', 0);
      uploadNext();
    }
  });
  xhr.addEventListener('abort', () => {
    // Keep progress but mark paused — handled by togglePause
  });
  xhr.open('POST', '/upload');
  xhr.send(formData);
}

// ── Drag & drop zone (supports folders via DataTransferItem) ───────────────────
const dzDrop = document.getElementById('dz-drop');
dzDrop.addEventListener('dragover', e => { e.preventDefault(); dzDrop.classList.add('over'); });
dzDrop.addEventListener('dragleave', () => dzDrop.classList.remove('over'));
dzDrop.addEventListener('drop', async e => {
  e.preventDefault(); dzDrop.classList.remove('over');
  const items = e.dataTransfer.items;
  const files = [];
  async function traverseEntry(entry, path) {
    if (entry.isFile) {
      await new Promise(res => entry.file(f => {
        Object.defineProperty(f, 'webkitRelativePath', { value: path + f.name });
        files.push(f); res();
      }));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      await new Promise(res => reader.readEntries(async entries => {
        for (const en of entries) await traverseEntry(en, path + entry.name + '/');
        res();
      }));
    }
  }
  for (const item of items) {
    const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
    if (entry) await traverseEntry(entry, '');
    else if (item.kind === 'file') files.push(item.getAsFile());
  }
  addFilesToQueue(files);
});

// Also enable drop on file dropzone
const dzFiles = document.getElementById('dz-files');
dzFiles.addEventListener('dragover', e => { e.preventDefault(); dzFiles.classList.add('over'); });
dzFiles.addEventListener('dragleave', () => dzFiles.classList.remove('over'));
dzFiles.addEventListener('drop', e => {
  e.preventDefault(); dzFiles.classList.remove('over');
  const fi = document.getElementById('fi');
  if (e.dataTransfer.files.length) { addFilesToQueue(e.dataTransfer.files); }
});

// ── Utilities ──────────────────────────────────────────────────────────────────
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function humanSize(n) {
  const units = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + ' ' + units[i];
}
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

// ── File actions ───────────────────────────────────────────────────────────────
function startRename(btn, oldName) {
  const item = btn.closest('.fitem');
  const fnEl = item.querySelector('.fn');
  const rwEl = item.querySelector('.rename-wrap');
  const inp  = rwEl.querySelector('.rename-input');
  inp.value  = oldName;
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
  const item    = btn.closest('.fitem');
  const newName = item.querySelector('.rename-input').value.trim();
  if (!newName || newName === oldName) { cancelRename(btn); return; }
  fetch('/rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ old: oldName, new: newName })
  })
  .then(r => r.json())
  .then(d => { if (d.ok) refreshList(); else showFlash('Rename failed: ' + (d.error || 'unknown'), 'err'); })
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
  .then(d => { if (d.ok) refreshList(); else showFlash('Delete failed: ' + (d.error || 'unknown'), 'err'); })
  .catch(() => showFlash('Delete request failed.', 'err'));
}

// ── Preview modal ──────────────────────────────────────────────────────────────
function previewMedia(enc, type) {
  const body = document.getElementById('preview-body');
  const url  = '/download/' + enc;
  if (type === 'image') {
    body.innerHTML = '<img src="' + url + '" alt="preview" onload="this.style.opacity=1" style="opacity:0;transition:opacity .3s"/>';
    setTimeout(() => body.querySelector('img').style.opacity = 1, 50);
  } else if (type === 'video') {
    body.innerHTML = '<video src="' + url + '" controls autoplay style="outline:none"></video>';
  }
  document.getElementById('preview-modal').classList.add('open');
}
function closeModal() {
  document.getElementById('preview-modal').classList.remove('open');
  document.getElementById('preview-body').innerHTML = '';
}
function closePreview(e) {
  if (e.target === document.getElementById('preview-modal')) closeModal();
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
</script>
</body>
</html>"""

# ── Render helpers ─────────────────────────────────────────────────────────────
def render_page(flash: str = "", https_active: bool = False) -> bytes:
    fl_html, count = render_file_list_html()
    phone_url  = f"http{'s' if https_active else ''}://{LOCAL_IP}:{ACTIVE_PORT}"
    https_badge = '<span class="https-badge">🔒 HTTPS</span>' if https_active else ''
    logout_btn  = '<button class="logout-btn" onclick="location=\'/logout\'">Log out</button>' if AUTH_ENABLED else ''
    page = HTML_TEMPLATE
    page = page.replace("FLASH_PLACEHOLDER", flash)
    page = page.replace("QR_PLACEHOLDER", _qr_svg(phone_url, size=160))
    page = page.replace("URL_PLACEHOLDER", html.escape(phone_url))
    page = page.replace("COUNT_PLACEHOLDER", str(count))
    page = page.replace("LIST_PLACEHOLDER", fl_html)
    page = page.replace("HTTPS_BADGE_PLACEHOLDER", https_badge)
    page = page.replace("AUTH_LOGOUT_PLACEHOLDER", logout_btn)
    return page.encode("utf-8")

def render_partial_files() -> bytes:
    fl_html, count = render_file_list_html()
    return (
        f'<div id="file-list-area">{fl_html}</div>'
        f'<span id="file-count">{count}</span>'
    ).encode("utf-8")

def render_login(error: str = "") -> bytes:
    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ''
    return LOGIN_HTML.replace("ERR_PLACEHOLDER", err_html).encode("utf-8")

# ── Handler ────────────────────────────────────────────────────────────────────
class FileShareHandler(http.server.BaseHTTPRequestHandler):
    timeout = 3600
    _https  = False

    def log_message(self, fmt, *args):
        print(f" [{self.address_string()}] {fmt % args}")

    def _send_html(self, body: bytes, status: int = 200, extra_headers: dict = {}):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _404(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def _authed(self) -> bool:
        return valid_session(self.headers.get("Cookie", ""))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/login":
            self._send_html(render_login())
            return

        if path == "/logout":
            # Remove session
            cookie = self.headers.get("Cookie", "")
            for part in cookie.split(";"):
                k, _, v = part.strip().partition("=")
                if k.strip() == SESSION_COOKIE:
                    _sessions.discard(v.strip())
            self._redirect("/login")
            return

        if AUTH_ENABLED and not self._authed():
            self._redirect("/login")
            return

        if path in ("/", "/index.html"):
            self._send_html(render_page(https_active=self._https))
        elif path == "/files":
            self._send_html(render_partial_files())
        elif path.startswith("/download/"):
            fname    = urllib.parse.unquote(path[len("/download/"):])
            # Prevent path traversal
            filepath = (SHARE_DIR / fname).resolve()
            if not str(filepath).startswith(str(SHARE_DIR.resolve())):
                self._404(); return
            if not filepath.is_file():
                self._404(); return
            mime = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
            # Serve inline for media (enables preview), attachment for rest
            ext = filepath.suffix.lower()
            if ext in (".png",".jpg",".jpeg",".gif",".webp",".avif",".svg",".mp4",".webm",".mov"):
                disp = f'inline; filename="{filepath.name}"'
            else:
                disp = f'attachment; filename="{filepath.name}"'
            size = filepath.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(4 * 1024 * 1024)
                    if not chunk: break
                    self.wfile.write(chunk)
        else:
            self._404()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length).decode("utf-8", errors="replace")
            params = urllib.parse.parse_qs(body)
            user   = params.get("username", [""])[0]
            pw     = params.get("password", [""])[0]
            if user == AUTH_USER and _hash(pw) == PASS_HASH:
                tok = new_session()
                self._send_html(
                    render_page(https_active=self._https),
                    extra_headers={"Set-Cookie": f"{SESSION_COOKIE}={tok}; Path=/; HttpOnly; SameSite=Strict"}
                )
            else:
                self._send_html(render_login("Invalid username or password."))
            return

        if AUTH_ENABLED and not self._authed():
            self._send_json({"ok": False, "error": "Unauthorized"}, 401)
            return

        if path == "/upload":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                content_type   = self.headers.get("Content-Type", "")
                saved_files    = stream_multipart_to_disk(self.rfile, content_type, content_length, SHARE_DIR)
                if saved_files:
                    parts = [f"{html.escape(name)} ({human_size(size)})" for name, size in saved_files]
                    self._send_json({"ok": True, "message": "Uploaded: " + ", ".join(parts)})
                else:
                    self._send_json({"ok": False, "error": "No valid file found in request"}, 400)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path == "/delete":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data   = json.loads(self.rfile.read(length))
                name   = data.get("name", "")
                fp     = (SHARE_DIR / name).resolve()
                if not str(fp).startswith(str(SHARE_DIR.resolve())):
                    self._send_json({"ok": False, "error": "Invalid path"}, 400); return
                if fp.is_file():
                    fp.unlink()
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False, "error": "File not found"}, 404)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        elif path == "/rename":
            try:
                length   = int(self.headers.get("Content-Length", 0))
                data     = json.loads(self.rfile.read(length))
                old_name = Path(data.get("old", "")).name
                new_name = Path(data.get("new", "")).name
                old_path = SHARE_DIR / old_name
                new_path = SHARE_DIR / new_name
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

# ── HTTPS handler subclass ─────────────────────────────────────────────────────
class HttpsFileShareHandler(FileShareHandler):
    _https = True

# ── Main ──────────────────────────────────────────────────────────────────────
ACTIVE_PORT = PREFERRED_PORT
LOCAL_IP    = "127.0.0.1"

def main():
    global ACTIVE_PORT, LOCAL_IP
    ACTIVE_PORT = find_free_port()
    LOCAL_IP    = get_local_ip()

    if ACTIVE_PORT != PREFERRED_PORT:
        print(f"Port {PREFERRED_PORT} in use → using {ACTIVE_PORT}")

    has_https = ensure_cert()

    # Start HTTP server
    http_server = http.server.ThreadingHTTPServer(("0.0.0.0", ACTIVE_PORT), FileShareHandler)

    # Start HTTPS server if cert is available
    https_server = None
    https_port   = None
    if has_https:
        try:
            https_port   = find_free_port(HTTPS_PORT)
            https_server = http.server.ThreadingHTTPServer(("0.0.0.0", https_port), HttpsFileShareHandler)
            ctx          = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(CERT_FILE), str(KEY_FILE))
            https_server.socket = ctx.wrap_socket(https_server.socket, server_side=True)
        except Exception as e:
            print(f"[HTTPS] Could not start HTTPS: {e}")
            https_server = None
            https_port   = None

    pc_url    = f"http://localhost:{ACTIVE_PORT}"
    phone_url = f"http://{LOCAL_IP}:{ACTIVE_PORT}"
    https_url = f"https://{LOCAL_IP}:{https_port}" if https_port else None

    print("\n" + "="*60)
    print(" HULK SEND — Local File Share (v2 with all features)")
    print("="*60)
    if AUTH_ENABLED:
        print(f"  Auth:      user='{AUTH_USER}'  pass='{AUTH_PASS}'")
        print(f"             (set HULK_USER / HULK_PASS env vars to change)")
    else:
        print("  Auth:      DISABLED (set HULK_AUTH=1 to enable)")
    print(f"  HTTP:      {pc_url}")
    print(f"  Phone:     {phone_url}  ← open this one")
    if https_url:
        print(f"  HTTPS:     {https_url}  ← secure (accept cert warning)")
    print(f"  Folder:    {SHARE_DIR.resolve()}")
    print("  Stop:      Ctrl+C")
    print("="*60 + "\n")

    if https_server:
        threading.Thread(target=https_server.serve_forever, daemon=True).start()

    threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(pc_url)), daemon=True).start()

    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.\n")
        http_server.server_close()
        if https_server:
            https_server.server_close()
        sys.exit(0)

if __name__ == "__main__":
    main()
