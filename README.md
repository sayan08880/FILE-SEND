# HULK SEND — Local File Sharing Server (V1 + V2)

A lightweight local file sharing server built using Python.
It enables seamless file transfer between devices on the same Wi-Fi network — without using the internet or cloud services.

---

## Overview

HULK SEND runs a local HTTP server and provides a browser-based interface to:

* Upload files (no size limit)
* Download files
* Rename files
* Delete files
* Access from desktop and mobile devices

---

## Versions

### Version 1 — Basic

A simple and efficient version focused on performance.

**Features:**

* Streaming upload (low memory usage)
* No file size limit
* Upload and download support
* Rename and delete files
* Automatic browser launch
* QR code access

**Use Case:**
Best for fast and simple file sharing.

---

### Version 2 — Advanced

Includes all Version 1 features with added security and enhancements.

**Features:**

* Authentication system
* HTTPS support (self-signed certificate)
* Session-based login
* Image and video preview
* Secure file handling (path validation)
* Environment-based credentials
* Optional authentication toggle

**Default Credentials:**

* Username: `hulk`
* Password: `smash`

**Use Case:**
Best for secure and feature-rich usage.

---

## How It Works

* Starts a local server on the host machine
* Detects the local IP address
* Provides a web interface

**Accessible via:**

* `localhost` (same device)
* Local IP (other devices on same Wi-Fi)

---

## Project Structure

```
HULK SEND/
│
├── SEND_V1.py
├── SEND_V2.py
└── HULK/        # Shared directory (auto-created)
```

---

## Usage

### Run Version 1

```bash
python SEND_V1.py
```

### Run Version 2

```bash
python SEND_V2.py
```

---

## Access from Mobile

Open in browser:

```
http://YOUR_LOCAL_IP:PORT
```

**Example:**

```
http://192.168.1.5:8080
```

**Requirements:**

* Same Wi-Fi network
* Firewall allows connections

---

## Authentication (Version 2 Only)

### Enable Authentication

```bash
export HULK_USER=your_username
export HULK_PASS=your_password
export HULK_AUTH=1
```

### Disable Authentication

```bash
export HULK_AUTH=0
```

---

## HTTPS Support (Version 2)

* Automatically generates a self-signed SSL certificate
* Runs on port `8443` (or next available port)

**Note:**
Browser warnings are expected due to self-signed certificates.

---

## Configuration

* Default Port: `8080`
* HTTPS Port: `8443`
* Shared Folder: `./HULK`
* Chunk Size: `8 MB`

---

## API Endpoints

| Endpoint  | Method | Description     |
| --------- | ------ | --------------- |
| /upload   | POST   | Upload file     |
| /download | GET    | Download file   |
| /delete   | POST   | Delete file     |
| /rename   | POST   | Rename file     |
| /files    | GET    | List files      |
| /login    | POST   | Login (V2 only) |

---

## Design

* Uses a streaming upload mechanism
* Files are written directly to disk
* Memory usage remains constant

**Result:**
Efficient handling of large file transfers.

---

## Limitations

* Works only on local network
* No internet-based transfer
* HTTPS uses self-signed certificate

---

## Version Comparison

| Use Case            | Recommended |
| ------------------- | ----------- |
| Simple file sharing | Version 1   |
| Secure sharing      | Version 2   |
| Low-resource system | Version 1   |
| Advanced features   | Version 2   |

---
## Important Libaris

```bash
pip install segno
```
```bash
python --version
```
* **Python 3.8+** Minimum
* **Python 3.10+** Best

## Summary

* **Version 1:** Simple and fast
* **Version 2:** Secure and feature-rich

---
