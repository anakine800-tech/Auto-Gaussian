"""Load an explicit trusted build into memory. Never resolve request paths on disk."""

from pathlib import Path
import re
import stat


def load_ui(directory: Path) -> dict[str, tuple[bytes, str]]:
    root = Path(directory)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("UI directory must be a canonical absolute directory")
    assets = root / "assets"
    if assets.is_symlink() or not assets.is_dir():
        raise ValueError("UI assets directory is required")
    files = [(root / "index.html", "/", "text/html")]
    for file in sorted(assets.iterdir()):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(js|css|svg)", file.name):
            raise ValueError("unsupported UI asset")
        files.append((file, "/assets/" + file.name,
                      {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}[file.suffix]))
    if len(files) > 32:
        raise ValueError("too many UI assets")
    result = {}
    total = 0
    for file, url, mime in files:
        metadata = file.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 5 * 1024 * 1024:
            raise ValueError("UI assets must be bounded regular files")
        body = file.read_bytes()
        total += len(body)
        if total > 10 * 1024 * 1024:
            raise ValueError("UI build too large")
        result[url] = (body, mime)
    return result
