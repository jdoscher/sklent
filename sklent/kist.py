"""Files a render set into Kist over its REST API.

Layout: `<root>/<owner>/<repo>/<design>` folders, one item per output, tagged so the
set can be sliced in Kist (`style:wireframe`, `format:reel`, …). Re-rendering a design
trashes the items of its previous set (restorable from Kist's trash).
"""

import mimetypes
from pathlib import Path

import httpx

from .config import get_settings


class KistError(RuntimeError):
    pass


class Kist:
    def __init__(self, url: str | None = None, token: str | None = None,
                 client: httpx.Client | None = None):
        s = get_settings()
        self.url = (url if url is not None else s.kist_url).rstrip("/")
        token = token if token is not None else s.kist_token
        self.http = client or httpx.Client(timeout=300)
        self.http.headers["Authorization"] = f"Bearer {token}"

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400:
            raise KistError(f"Kist {r.request.method} {r.request.url.path}: "
                            f"{r.status_code} {r.text[:300]}")
        return r

    def health(self) -> bool:
        try:
            return self.http.get(f"{self.url}/api/health", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def ensure_folder(self, path: list[str]) -> str:
        """Folder id for a path of names, creating what's missing."""
        folders = self._check(self.http.get(f"{self.url}/api/folders")).json()
        parent: str | None = None
        for name in path:
            match = next((f for f in folders
                          if f["parent_id"] == parent and f["name"] == name), None)
            if match is None:
                match = self._check(self.http.post(
                    f"{self.url}/api/folders", json={"name": name, "parent_id": parent})).json()
                folders.append(match)
            parent = match["id"]
        assert parent is not None
        return parent

    def upload(self, file: Path, *, folder_id: str, tags: list[str], notes: str,
               source_url: str) -> dict:
        mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        with file.open("rb") as fh:
            r = self.http.post(
                f"{self.url}/api/items",
                files={"file": (file.name, fh, mime)},
                data={"folder_ids": folder_id, "tags": ",".join(tags), "notes": notes,
                      "source_url": source_url},
            )
        return self._check(r).json()["item"]

    def trash(self, item_id: str) -> None:
        r = self.http.delete(f"{self.url}/api/items/{item_id}")
        if r.status_code != 404:
            self._check(r)
