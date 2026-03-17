HULK SEND — Local File Transfer Server
======================================

HULK SEND is a lightweight Python-based file transfer server.
It allows you to upload, download, preview, and manage files
across devices on the same network using a web browser.


FEATURES
--------
- Upload multiple files or full folders
- Mobile access via QR code
- Optional login authentication
- Pause / Resume uploads
- No file size limit (streaming)
- Image and video preview support
- Folder structure preserved
- Rename and delete files
- Works over HTTP and HTTPS
- Pure Python (no dependencies required)


REQUIREMENTS
------------
- Python 3.8+
- Optional: OpenSSL (for HTTPS)


INSTALLATION
------------
git clone https://github.com/your-username/hulk-send.git
cd hulk-send
python SEND_V2.py


USAGE
-----
Open in browser:
http://localhost:8080

From mobile (same Wi-Fi):
http://<your-local-ip>:8080

Or scan QR code shown in UI.


AUTHENTICATION
--------------
Default credentials:
Username: hulk
Password: smash

Change credentials:
export HULK_USER=myuser
export HULK_PASS=mypass

Disable authentication:
export HULK_AUTH=0


HTTPS (OPTIONAL)
----------------
Access:
https://localhost:8443

Note:
Browser may show a warning (self-signed certificate).


FILE STORAGE
------------
All files are stored in:
./HULK/

- Folder uploads keep structure
- Files are streamed directly to disk


API ENDPOINTS
-------------
/upload     POST   Upload files
/download   GET    Download file
/rename     POST   Rename file
/delete     POST   Delete file
/files      GET    Refresh file list
/login      POST   Login


RENAME REQUEST EXAMPLE
----------------------
POST /rename

{
  "old": "file.txt",
  "new": "newname.txt"
}


NOTES
-----
- Works only on same network (LAN)
- Supports large files
- No database used


PREVIEW SUPPORT
---------------
Image  : Yes
Video  : Yes
Others : No


TECH STACK
----------
- Python (http.server)
- HTML + CSS
- Vanilla JavaScript


FUTURE IMPROVEMENTS
-------------------
- Public sharing (internet)
- Multi-user system
- File search and filtering


LICENSE
-------
MIT License


AUTHOR
------
Sayan
