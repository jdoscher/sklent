"""Files a render set into Kist over its REST API.

Layout: `<root>/<owner>/<repo>/<design>` folders, one item per output, tagged so the
set can be sliced in Kist (`style:wireframe`, `format:reel`, `rev:<commit10>`, …).

Revisions (0.2): a re-render never trashes the previous set's items, so links to them
keep working. Each new item is linked `version_of` the item it follows (same style and
format, previous set) and joins its stack as the cover, the way Kist's own
"upload a new version" does, so Kist's versions list and compare work on the chain.
Only the keep policy's `revisions_prune_kist` (off by default) trashes anything.
"""

import mimetypes
import re
from pathlib import Path

import httpx

from .config import get_settings


class KistError(RuntimeError):
    pass


REV_RE = re.compile(r"\bat ([0-9a-f]{7,40})\b")


def rev_tag(commit_sha: str | None) -> str | None:
    return f"rev:{commit_sha[:10]}" if commit_sha else None


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

    # ------------------------------------------------------------ revisions

    def get_item(self, item_id: str) -> dict | None:
        r = self.http.get(f"{self.url}/api/items/{item_id}")
        if r.status_code == 404:
            return None
        return self._check(r).json()

    def add_tags(self, item_id: str, tags: list[str]) -> None:
        """Add tags without touching the item's others (Kist's PATCH .../tags)."""
        self._check(self.http.patch(f"{self.url}/api/items/{item_id}/tags",
                                    json={"add": tags, "remove": []}))

    def file_version(self, new_id: str, old_id: str) -> None:
        """Link `new_id` version_of `old_id` and make it the cover of their stack, as
        Kist's own new-version upload does (services/versions.py). Linking twice is a
        no-op in Kist."""
        if not new_id or not old_id or new_id == old_id:
            return
        self._check(self.http.post(f"{self.url}/api/items/{new_id}/links",
                                   json={"dst_id": old_id, "kind": "version_of"}))
        old = self.get_item(old_id) or {}
        new = self.get_item(new_id) or {}
        stack = old.get("stack_id") or new.get("stack_id")
        if stack:
            self._check(self.http.patch(f"{self.url}/api/stacks/{stack}",
                                        json={"add": [new_id, old_id], "cover": new_id}))
        else:
            self._check(self.http.post(f"{self.url}/api/stacks",
                                       json={"item_ids": [old_id, new_id], "cover": new_id}))

    def commit_of(self, item_id: str) -> str | None:
        """The commit an item was rendered at, from the notes sklent wrote on it
        (`owner/repo:path at <commit10>, rendered by sklent`): for items from before
        revisions, which carry no `rev:` tag."""
        item = self.get_item(item_id) or {}
        for tag in item.get("tags") or []:
            if tag.startswith("rev:"):
                return tag[4:]
        m = REV_RE.search(item.get("notes") or "")
        return m.group(1) if m else None
