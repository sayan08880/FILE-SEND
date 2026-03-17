# HULK SEND – Local File Sharing Server

A high-performance local file sharing server built using pure Python.
It allows you to transfer files between devices on the same Wi-Fi network without using the internet, external apps, or cloud services.

---

## Overview

HULK SEND runs a lightweight HTTP server on your machine and provides a clean web interface to:

* Upload files (no size limit)
* Download files
* Rename files
* Delete files

It is optimized for large file transfers using a streaming upload system, which ensures minimal memory usage.

---

## Key Features

* No file size limit (streaming upload)
* Works on any device (PC, Android, iOS)
* No internet required (LAN-based)
* QR code for quick mobile access
* Clean and responsive UI
* File management (upload, download, rename, delete)
* Automatic local IP detection
* Runs on available port automatically

---

## How It Works

### 1. Server Initialization

When you run the script:

* It finds a free port starting from `8080`
* Detects your local IP address
* Starts a multi-threaded HTTP server

```python
server = http.server.ThreadingHTTPServer(("0.0.0.0", ACTIVE_PORT), FileShareHandler)
```

This allows multiple devices to connect simultaneously.

---

### 2. Local Network Access

You get two URLs:

* PC: `http://localhost:PORT`
* Mobile: `http://YOUR_LOCAL_IP:PORT`

Any device connected to the same Wi-Fi can access the server using the mobile URL.

---

### 3. File Upload (Streaming System)

This is the core strength of the project.

Instead of loading the entire file into memory, it:

* Reads the file in chunks (`8 MB`)
* Writes directly to disk
* Keeps RAM usage constant

```python
CHUNK_SIZE = 8 * 1024 * 1024
```

The function responsible:

```python
stream_multipart_to_disk(...)
```

#### Why this matters:

* You can upload very large files (GBs)
* No memory crash
* Stable performance

---

### 4. Multipart Parsing

The server manually parses `multipart/form-data`:

* Detects boundaries
* Extracts file metadata
* Streams content safely to disk

No use of `cgi` or external libraries.

---

### 5. File Storage

All uploaded files are stored in:

```bash
./HULK
```

You can also manually copy files into this folder, and they will appear in the UI instantly.

---

### 6. File Operations

#### Download

* Uses chunked reading (4 MB per chunk)
* Prevents memory overload

#### Rename

* Validates file names
* Prevents overwrite conflicts

#### Delete

* Securely removes file from disk

---

### 7. Frontend (UI)

The interface is built using:

* HTML
* CSS (modern UI design)
* Vanilla JavaScript

#### Features:

* Drag & drop upload
* Upload progress bar
* Live file list refresh (AJAX)
* Rename inline editing
* Responsive design

---

### 8. QR Code System

* Generates QR code for mobile access
* Uses `segno` (optional)

If not installed, a fallback SVG is shown.

---

## Project Structure

```bash
.
├── your_script.py
├── HULK/
```

---

## Configuration

You can modify these values:

```python
PREFERRED_PORT = 8080
SHARE_DIR = Path("./HULK")
CHUNK_SIZE = 8 * 1024 * 1024
```

---

## Requirements

* Python 3.7+

Optional:

```bash
pip install segno
```

---

## Running the Project

```bash
python your_script.py
```

After running, open:

```bash
http://localhost:PORT
```

or on mobile:

```bash
http://YOUR_LOCAL_IP:PORT
```

---

## Security Notes

* Only works within local network
* No authentication system
* Do not expose to public internet
* Filenames are sanitized to prevent path traversal

---

## Performance Highlights

* Constant RAM usage regardless of file size
* Multi-threaded request handling
* Efficient disk streaming
* Minimal dependencies

---

## Limitations

* No user authentication
* No encryption (HTTP only)
* No file preview
* Not designed for public hosting

---

## Future Improvements

* Authentication system
* HTTPS support
* File preview (images, videos)
* Upload pause/resume
* Folder upload support
* Drag & drop multiple folders

---

## Use Cases

* Transfer files between phone and PC
* Share large files quickly over Wi-Fi
* Offline file sharing
* Development/testing of HTTP systems

---

## Conclusion

HULK SEND is designed to be simple, fast, and reliable.
It focuses on solving real file transfer problems without unnecessary complexity.

---

## Contact

If you want improvements or collaboration:

Email: [dasguptasayan.080@gmail.com](mailto:dasguptasayan.080@gmail.com)
Mobile & WhatsApp: +91 6290688153

---
