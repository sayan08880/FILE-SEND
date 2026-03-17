HULK SEND — Local File Sharing Server (V1 + V2)

A lightweight and high-performance local file sharing server built using pure Python.

It allows file transfer between devices connected to the same Wi-Fi network without using the internet, cloud services, or external applications.

Overview

HULK SEND runs a local HTTP server and provides a web-based interface with the following capabilities:

Upload files (no size limit)

Download files

Rename files

Delete files

Access from both desktop and mobile browsers

Versions
Version 1 — Basic

A simple and efficient implementation focused on performance and stability.

Features

Streaming file upload (low memory usage)

No file size limit

Upload and download support

Rename and delete files

Automatic browser launch

QR code for mobile access

Suitable For

Large file transfers

Low-resource systems

Quick and simple usage

Version 2 — Advanced

An extended version with security and enhanced functionality.

Features

Includes all Version 1 features

User authentication system

HTTPS support (self-signed certificate)

Session-based login handling

Image and video preview support

Secure file handling with path validation

Environment-based credential configuration

Optional authentication toggle

Default Credentials

Username: hulk
Password: smash

How It Works

Starts a local server on the host machine

Automatically detects the local IP address

Provides a browser-based interface

Allows access from:

Local machine via localhost

Other devices via local IP

Project Structure
HULK SEND/
│
├── SEND_V1.py
├── SEND_V2.py
└── HULK/        (auto-created shared directory)
Usage
Run Version 1
python SEND_V1.py
Run Version 2
python SEND_V2.py
Access from Mobile Device

After running the server, open the following in your browser:

http://YOUR_LOCAL_IP:PORT

Example:

http://192.168.1.5:8080

Requirements:

Both devices must be connected to the same Wi-Fi network

Firewall settings must allow incoming connections

Authentication (Version 2 Only)

Configure using environment variables:

export HULK_USER=your_username
export HULK_PASS=your_password
export HULK_AUTH=1

Disable authentication:

export HULK_AUTH=0
HTTPS Support (Version 2)

Automatically generates a self-signed SSL certificate

Runs on port 8443 (or next available port)

Note: Browsers may show a security warning due to the self-signed certificate.

Configuration
Setting	Default Value
Port	8080
HTTPS Port	8443
Share Directory	./HULK
Chunk Size	8 MB
API Endpoints
Endpoint	Method	Description
/upload	POST	Upload file
/download	GET	Download file
/delete	POST	Delete file
/rename	POST	Rename file
/files	GET	List files
/login	POST	Login (V2 only)
Design Concept

The system uses a streaming upload mechanism:

Files are written directly to disk during upload

Memory usage remains constant

Efficient for handling very large files

Limitations

Works only within a local network

HTTPS uses a self-signed certificate

No internet-based file transfer

Version Comparison
Use Case	Recommended Version
Simple file sharing	Version 1
Secure file sharing	Version 2
Low-resource system	Version 1
Feature-rich usage	Version 2
Conclusion

Version 1 provides a fast and simple solution for local file transfer.
Version 2 adds security and advanced features for more controlled usage.

Both versions are designed to be efficient and easy to use depending on the requirement.
