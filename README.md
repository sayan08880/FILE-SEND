# HULK SEND v1 – Advanced Local File Transfer

A feature-rich local network file sharing server with browser interface.

## Core Capabilities

- Username and password authentication with session cookies
- Optional HTTPS using auto-generated self-signed certificate
- Folder upload with directory structure preservation
- Drag-and-drop support for files and entire folders
- Upload queue with individual file progress, pause, resume and cancel
- Media preview for images and playable video files
- Rename and delete files directly from the web interface
- Streaming upload to disk with very low memory usage
- QR code display for quick mobile access
- Responsive dark-themed interface

## Main Differences Compared to v2

Feature                            | v1          | v2
-----------------------------------|-------------|------
Authentication                    | Yes         | No
HTTPS (self-signed)               | Yes         | No
Folder upload with structure      | Yes         | No
Upload queue + pause/resume       | Yes         | No
Per-file progress bars            | Yes         | No (only total)
Image and video preview           | Yes         | No
Code length and complexity        | Higher      | Much lower

## Requirements

- Python 3.8 or newer
- Optional: segno library for better QR codes (pip install segno)

## Quick Start

1. Place the script in any folder
2. (optional) Set custom credentials

   ```bash
   export HULK_USER="yourname"
   export HULK_PASS="yourpassword"

(optional) Disable authenticationBashexport HULK_AUTH=0
Run the scriptBashpython SEND_V1.py

The console will show:

Local address
Network address for other devices
Optional HTTPS address if certificate was created

Open the network address from phone or other computer on the same Wi-Fi.
Storage Location
All uploaded files are saved in the folder named HULK next to the script.
Certificate Files
If openssl is installed, the script automatically creates:

hulk_cert.pem
hulk_key.pem

These are used for the optional HTTPS server.
Security Information

Intended for local network (LAN) use only
Self-signed certificate triggers browser warning
Authentication uses simple SHA-256 hashing
No protection against internet exposure

License
MIT
text### README for simple version (SEND_V2.py)
HULK SEND v2 – Minimal Local File Transfer
A very simple, lightweight local network file sharing server.
Core Capabilities

Streaming upload directly to disk (almost constant memory usage)
No practical file size limit
Rename and delete files from browser
QR code for easy phone access
Single-file progress bar during upload
Clean dark interface
Zero external dependencies

Main Differences Compared to v1













































Featurev1v2AuthenticationYesNoHTTPS supportYesNoFolder uploadYesNoUpload queue with pause/resumeYesNoMedia previewYesNoIndividual file progressYesNoCode simplicityModerateVery high
Requirements

Python 3.6 or newer
No additional packages needed

Quick Start

Place the script in any folder
Run itBashpython SEND_V2.py

Console output will show:

Local address
Network address

Open the network address from any device on the same Wi-Fi network.
Storage Location
All files are saved in the folder named HULK next to the script.
Security Information

No authentication – anyone on the same network can access
Designed only for temporary local sharing
Never expose to the public internet

When to Choose v2

You want the smallest possible code to understand or modify
You do not need login protection
You prefer zero dependencies
You run on restricted or older Python environments

License
MIT
textBoth versions are now written without emojis, without excessive bullet lists, and in a consistent plain-text + table style suitable for GitHub README files.  
You can copy each block directly into its own `README.md` file.

Let me know if you want any section expanded, shortened, or merged differently.
