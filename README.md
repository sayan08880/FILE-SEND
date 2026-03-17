# FileBeam v2 – Local File Sharing Server

A simple, fast, and lightweight **local file sharing server** built with pure Python.
No external frameworks. No setup complexity. Just run and share files instantly across devices on the same network.

---

## Features

* Upload multiple files via browser
* Download files from any device
* Rename files directly from UI
* Delete files instantly
* QR code for quick mobile access
* Works on any device (PC, Android, iOS)
* No internet required (LAN only)
* Clean and modern UI

---

## How It Works

* Starts a local HTTP server
* Automatically finds your **local IP**
* Generates a **QR code + URL**
* Access from phone or other devices on same Wi-Fi
* Files are stored in a local folder: `./shared_files`

---

## Requirements

* Python 3.7+
* Optional (for QR code):

  ```bash
  pip install segno
  ```

---

## Run the Project

```bash
python your_script_name.py
```

---

## Access URLs

After running, you’ll see:

```
PC:     http://localhost:PORT
Phone:  http://YOUR_LOCAL_IP:PORT
```

Open the **Phone URL** on other devices (same Wi-Fi)

---

## Project Structure

```
.
├── your_script.py
├── shared_files/
```

---

## Upload Files

* Drag & drop files into the UI
* Or click to select files
* Supports multiple uploads

---

## Download Files

* Click **Download** button next to any file

---

## Rename Files

* Click **Rename**
* Enter new name
* Save instantly

---

## Delete Files

* Click **Delete**
* Confirm action

---

## Security Notes

* Only accessible within your local network
* No authentication (use in trusted networks only)
* Filenames are sanitized for safety

---

## Technical Highlights

* Built using `http.server` (no frameworks)
* Custom multipart/form-data parser (no `cgi`)
* Dynamic HTML rendering
* AJAX-based file operations
* Streaming file download (memory efficient)

---

## Customization

You can modify:

```python
PREFERRED_PORT = 8080
SHARE_DIR = Path("./shared_files")
```

---

## Limitations

* No user authentication
* Not suitable for public internet exposure
* Basic file management only

---

## Future Improvements (Ideas)

* User authentication
* Drag & drop folder upload
* Progress persistence
* Dark/light theme toggle
* File preview (images/videos)

---

## License

Free to use and modify.

---

## Author

Built with simplicity in mind.
Feel free to improve and share.

---

## Support

If this helped you:

* Star the repo
* Share with others
* Contribute improvements

---
