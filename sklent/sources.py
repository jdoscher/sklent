"""Where designs come from: GitHub and Forgejo accounts, repos, folders and files.

Discovery uses each forge's git-tree API, so nothing is cloned: a scan lists the
design files (`.sc` / `.solidcraft`, and since 0.2 `.step` / `.stp`, `.stl`, `.3mf`) with
their blob SHAs (cheap change detection), and a render fetches just the design file (plus
the designs it links, see `sklent.features.inputs.links`) at the scanned commit.

A source can name a ref: a branch or tag (`/tree/<ref>`, `/src/branch|tag/<ref>`,
`/releases/tag/<tag>`), a commit, or a pull request (`/pull/<n>` on GitHub, `/pulls/<n>`
on Forgejo). A pull request is stored as the ref `pull/<n>` and resolves to its head
commit. An account source may carry `?prefix=<name prefix>` (a class set: only repos
whose name starts with it).
"""

import fnmatch
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx

from .config import get_settings

SOLIDCRAFT_SUFFIXES = (".sc", ".solidcraft")
STEP_SUFFIXES = (".step", ".stp")
MESH_SUFFIXES = (".stl", ".3mf")
DESIGN_SUFFIXES = SOLIDCRAFT_SUFFIXES + STEP_SUFFIXES + MESH_SUFFIXES
# The format families a source can find (settings `inputs_step`, `inputs_mesh`; `.sklent.yaml`
# `formats:`). SolidCraft's own files are always found.
FORMATS = {"sc": SOLIDCRAFT_SUFFIXES, "step": STEP_SUFFIXES, "stl": (".stl",), "3mf": (".3mf",)}
ALL_FORMATS = tuple(FORMATS)
PULL_REF = re.compile(r"^pull/(\d+)$")
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
# Folder names skipped by default: test corpora and fixtures are rarely worth a showcase.
DEFAULT_EXCLUDE = ["tests", "test", "fixtures", "corpus"]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SourceError(ValueError):
    pass


@dataclass(frozen=True)
class SourceSpec:
    provider: str  # github | forgejo
    host: str  # scheme://host[:port] of the web UI
    kind: str  # account | repo
    owner: str
    repo: str | None = None
    ref: str | None = None
    path: str | None = None
    prefix: str | None = None  # account sources only: repo-name prefix (a class set)

    @property
    def pull(self) -> int | None:
        m = PULL_REF.match(self.ref or "")
        return int(m.group(1)) if m else None

    @property
    def canonical_url(self) -> str:
        url = f"{self.host}/{self.owner}"
        if self.repo:
            url += f"/{self.repo}"
            if self.pull is not None:
                url += f"/pull/{self.pull}" if self.provider == "github" else f"/pulls/{self.pull}"
            elif self.ref or self.path:
                verb = "tree" if self.provider == "github" else "src/branch"
                url += f"/{verb}/{self.ref or 'HEAD'}"
                if self.path:
                    url += f"/{self.path}"
        elif self.prefix:
            url += "?" + urlencode({"prefix": self.prefix})
        return url


@dataclass(frozen=True)
class RepoInfo:
    owner: str
    name: str
    default_branch: str
    fork: bool = False
    archived: bool = False


@dataclass(frozen=True)
class TreeFile:
    path: str
    sha: str
    size: int


def parse_source(raw: str) -> SourceSpec:
    """Turn what a user pastes into a source.

    Accepts web URLs for accounts, repos, folders (`tree/…`, `src/branch/…`) and files
    (`blob/…`), git SSH/HTTPS clone URLs, and `owner/repo` shorthand for GitHub. Any
    host other than github.com is treated as Forgejo/Gitea; an SSH URL on a non-GitHub
    host maps to the configured Forgejo web URL, or to `https://<host>` when none is set.
    """
    raw = raw.strip()
    if not raw:
        raise SourceError("empty source URL")
    forgejo = get_settings().forgejo_url.rstrip("/")

    # git@host:owner/repo.git (scp-like SSH)
    m = re.match(r"^[\w.-]+@([\w.-]+):(?!\d+/)(.+)$", raw)
    if m:
        host, path = m.groups()
        provider, base = ("github", "https://github.com") if host == "github.com" else ("forgejo", forgejo or f"https://{host}")
        return _from_path(provider, base, path)
    if re.match(r"^[\w.-]+/[\w.-]+$", raw):
        return _from_path("github", "https://github.com", raw)
    if "://" not in raw:
        raw = "https://" + raw

    parts = urlsplit(raw)
    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise SourceError(f"not a URL: {raw}")
    prefix = (parse_qs(parts.query).get("prefix") or [None])[0]
    if hostname in ("github.com", "www.github.com"):
        spec = _from_path("github", "https://github.com", parts.path)
    elif parts.scheme == "ssh":
        spec = _from_path("forgejo", forgejo or f"https://{hostname}", parts.path)
    else:
        base = f"{parts.scheme}://{parts.netloc.split('@')[-1]}"
        spec = _from_path("forgejo", base, parts.path)
    if prefix and spec.kind == "account":
        spec = SourceSpec(spec.provider, spec.host, spec.kind, spec.owner, prefix=prefix.strip())
    return spec


def _from_path(provider: str, base: str, path: str) -> SourceSpec:
    segs = [s for s in path.strip("/").split("/") if s]
    if not segs:
        raise SourceError("the URL names no account or repository")
    if provider == "github" and segs[0] == "orgs" and len(segs) >= 2:
        segs = segs[1:2]  # github.com/orgs/<org>/repositories → the org
    owner = segs[0]
    if len(segs) == 1:
        return SourceSpec(provider, base, "account", owner)
    repo = segs[1].removesuffix(".git")
    rest = segs[2:]
    ref = path_in_repo = None
    if rest:
        # github: blob|tree/<ref>/<path>, pull/<n>, commit/<sha>, releases/tag/<tag>
        # forgejo: src|raw/branch|commit|tag/<ref>/<path>, pulls/<n>, commit/<sha>, releases/tag/<tag>
        pull_word = "pull" if provider == "github" else "pulls"
        if rest[0] == pull_word and len(rest) >= 2 and rest[1].isdigit():
            return SourceSpec(provider, base, "repo", owner, repo, f"pull/{int(rest[1])}")
        if rest[0] == "commit" and len(rest) >= 2:
            return SourceSpec(provider, base, "repo", owner, repo, rest[1])
        if rest[:2] == ["releases", "tag"] and len(rest) >= 3:
            return SourceSpec(provider, base, "repo", owner, repo, rest[2])
        if rest[0] in ("blob", "tree", "raw") and provider == "github" and len(rest) >= 2:
            ref, tail = rest[1], rest[2:]
        elif rest[0] in ("src", "raw", "media") and len(rest) >= 3 and rest[1] in ("branch", "commit", "tag"):
            ref, tail = rest[2], rest[3:]
        else:
            raise SourceError(f"don't know how to read {'/'.join(rest)} in a repository URL")
        path_in_repo = "/".join(tail) or None
    return SourceSpec(provider, base, "repo", owner, repo, ref, path_in_repo)


def design_format(path: str) -> str | None:
    """`sc`, `step`, `stl` or `3mf` from a file name; None for anything else."""
    low = path.lower()
    for fmt, suffixes in FORMATS.items():
        if low.endswith(suffixes):
            return fmt
    return None


def is_design_path(path: str, formats: tuple[str, ...] | list[str] | None = None) -> bool:
    """A design file in one of `formats` (default: every format Sklent reads)."""
    fmt = design_format(path)
    return fmt is not None and (formats is None or fmt == "sc" or fmt in formats)


def drop_mesh_exports(paths: list[str]) -> set[str]:
    """The STEP/STL/3MF files that are exports of a SolidCraft design next to them (same
    folder, same name: `case.sc` and `case.stl`). They show the same part, so only the
    design renders."""
    designs = {p.rsplit(".", 1)[0].lower() for p in paths if design_format(p) == "sc"}
    return {p for p in paths if design_format(p) not in (None, "sc") and p.rsplit(".", 1)[0].lower() in designs}


def excluded(path: str, exclude: list[str], scope: str | None = None) -> bool:
    """Exclusions apply below the source's own folder or file: pointing at something
    inside `tests/` on purpose renders it."""
    if scope:
        path = path[len(scope.strip("/")):].lstrip("/") or path.rsplit("/", 1)[-1]
    folders = path.split("/")[:-1]
    for pattern in exclude:
        if any(c in pattern for c in "*?["):
            if fnmatch.fnmatch(path, pattern):
                return True
        elif pattern in folders:
            return True
    return False


def in_scope(path: str, scope: str | None) -> bool:
    if not scope:
        return True
    scope = scope.strip("/")
    return path == scope or path.startswith(scope + "/")


def looks_like_design(data: bytes, path: str | None = None) -> bool:
    """Whether the bytes are what the file name says. `.sc` is also SuperCollider's
    extension, so insist on SolidCraft's own header; STEP files start with ISO 10303-21;
    an STL is ASCII (`solid … facet`) or binary (84-byte header + 50 bytes a triangle);
    a 3MF is a zip with a 3D model part. Without a path, only SolidCraft is accepted."""
    fmt = design_format(path) if path else "sc"
    if fmt == "step":
        return data[:256].lstrip().upper().startswith(b"ISO-10303-21")
    if fmt == "stl":
        if len(data) >= 84 and len(data) == 84 + 50 * int.from_bytes(data[80:84], "little"):
            return True
        head = data[:1024].lstrip().lower()
        return head.startswith(b"solid") and (b"facet" in head or b"endsolid" in head)
    if fmt == "3mf":
        if data[:2] != b"PK":
            return False
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return False
        return any(n.lower().endswith(".model") for n in names)
    if data[:2] == b"PK":  # packaged design (zip)
        return True
    head = data[:512].lstrip()
    return head.startswith(b"{") and b'"solidcraft/' in head


def git_blob_sha(data: bytes) -> str:
    """The SHA git gives these bytes as a blob (what the tree API lists)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def parse_time(value: str) -> datetime:
    """An ISO 8601 date-time (`Z` allowed); a naive one is taken as UTC."""
    from datetime import UTC

    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Forge:
    """The handful of forge API calls a scan and a render need."""

    def __init__(self, spec_provider: str, host: str, client: httpx.Client | None = None):
        self.provider = spec_provider
        self.host = host.rstrip("/")
        settings = get_settings()
        headers = {"User-Agent": "sklent"}
        if spec_provider == "github":
            self.api = "https://api.github.com"
            headers["Accept"] = "application/vnd.github+json"
            if settings.github_token:
                headers["Authorization"] = f"Bearer {settings.github_token}"
        else:
            self.api = f"{self.host}/api/v1"
            # Only ever send the Forgejo token to the Forgejo it was made for.
            if settings.forgejo_token and self.host == settings.forgejo_url.rstrip("/"):
                headers["Authorization"] = f"token {settings.forgejo_token}"
        self.http = client or httpx.Client(timeout=60, follow_redirects=True)
        self.http.headers.update(headers)

    def _get(self, path: str, **kw) -> httpx.Response:
        r = self.http.get(f"{self.api}{path}", **kw)
        if r.status_code == 404:
            raise SourceError(f"not found (or private without a token): {self.host}{path}")
        if r.status_code in (401, 403):
            raise SourceError(f"{self.host} refused {path} ({r.status_code}); check the API token")
        r.raise_for_status()
        return r

    def list_repos(self, owner: str) -> list[RepoInfo]:
        out: list[RepoInfo] = []
        if self.provider == "github":
            paths = [f"/users/{quote(owner)}/repos?type=owner&per_page=100"]
            if "Authorization" in self.http.headers:
                me = self.http.get(f"{self.api}/user")
                if me.status_code == 200 and me.json().get("login", "").lower() == owner.lower():
                    paths = ["/user/repos?affiliation=owner&per_page=100"]
            page_param = "page"
        else:
            paths = [f"/users/{quote(owner)}/repos?limit=50", f"/orgs/{quote(owner)}/repos?limit=50"]
            page_param = "page"
        last_error: Exception | None = None
        for base in paths:
            try:
                page = 1
                while True:
                    batch = self._get(f"{base}&{page_param}={page}").json()
                    if not batch:
                        break
                    for r in batch:
                        out.append(RepoInfo(
                            owner=r["owner"]["login"], name=r["name"],
                            default_branch=r.get("default_branch") or "main",
                            fork=bool(r.get("fork")), archived=bool(r.get("archived")),
                        ))
                    page += 1
                return out
            except SourceError as exc:
                last_error = exc
        raise last_error or SourceError(f"no repositories found for {owner}")

    def repo_info(self, owner: str, repo: str) -> RepoInfo:
        r = self._get(f"/repos/{quote(owner)}/{quote(repo)}").json()
        return RepoInfo(r["owner"]["login"], r["name"], r.get("default_branch") or "main",
                        bool(r.get("fork")), bool(r.get("archived")))

    def resolve(self, owner: str, repo: str, ref: str) -> str:
        """A branch, tag, SHA or `pull/<n>` (a pull request's head) → the commit SHA."""
        if SHA_RE.match(ref):
            return ref
        m = PULL_REF.match(ref)
        if m:
            return self.pull(owner, repo, int(m.group(1)))["head_sha"]
        if self.provider == "github":
            r = self._get(f"/repos/{quote(owner)}/{quote(repo)}/commits/{quote(ref, safe='')}",
                          headers={"Accept": "application/vnd.github.sha"})
            return r.text.strip()
        r = self._get(f"/repos/{quote(owner)}/{quote(repo)}/commits?sha={quote(ref, safe='')}&limit=1")
        commits = r.json()
        if not commits:
            raise SourceError(f"{owner}/{repo} has no commits on {ref}")
        return commits[0]["sha"]

    def tree(self, owner: str, repo: str, sha: str) -> list[TreeFile]:
        files: list[TreeFile] = []
        if self.provider == "github":
            data = self._get(f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{sha}?recursive=1").json()
            entries = data.get("tree", [])
        else:
            entries, page = [], 1
            while True:
                data = self._get(f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{sha}"
                                 f"?recursive=true&per_page=10000&page={page}").json()
                entries += data.get("tree") or []
                if not data.get("truncated"):
                    break
                page += 1
        for e in entries:
            if e.get("type") == "blob":
                files.append(TreeFile(e["path"], e["sha"], int(e.get("size") or 0)))
        return files

    def pull(self, owner: str, repo: str, number: int) -> dict:
        """A pull request: number, title, state, html_url, head/base sha and ref."""
        r = self._get(f"/repos/{quote(owner)}/{quote(repo)}/pulls/{number}").json()
        head, base = r.get("head") or {}, r.get("base") or {}
        return {"number": number, "title": r.get("title") or "", "state": r.get("state") or "",
                "html_url": r.get("html_url") or "", "head_sha": head.get("sha"),
                "head_ref": head.get("ref") or "", "base_sha": base.get("sha"),
                "base_ref": base.get("ref") or ""}

    def pull_files(self, owner: str, repo: str, number: int, max_pages: int = 30) -> list[str]:
        """Paths a pull request adds or changes (renamed files under their new name)."""
        out: list[str] = []
        for page in range(1, max_pages + 1):
            q = f"per_page=100&page={page}" if self.provider == "github" else f"limit=50&page={page}"
            batch = self._get(f"/repos/{quote(owner)}/{quote(repo)}/pulls/{number}/files?{q}").json()
            if not batch:
                break
            out += [f["filename"] for f in batch if f.get("status") != "removed" and f.get("filename")]
            if self.provider == "github" and len(batch) < 100:
                break
        return out

    def commit_before(self, owner: str, repo: str, ref: str, until: datetime,
                      max_pages: int = 20) -> tuple[str, str] | None:
        """The newest commit on `ref` whose committer date is at or before `until`, as
        (sha, ISO date), or None when the branch has none that old. Asks the forge to
        filter (`until=`) and checks the dates itself, paging back for a forge that
        ignores the parameter."""
        from datetime import UTC

        stamp = until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = f"/repos/{quote(owner)}/{quote(repo)}/commits?sha={quote(ref, safe='')}&until={quote(stamp)}"
        for page in range(1, max_pages + 1):
            q = f"&per_page=50&page={page}" if self.provider == "github" else f"&limit=50&page={page}"
            try:
                batch = self._get(base + q).json()
            except SourceError:
                if page == 1:
                    raise
                return None
            if not batch:
                return None
            for c in batch:
                when = ((c.get("commit") or {}).get("committer") or {}).get("date") or c.get("created")
                if when and parse_time(when) <= until:
                    return c["sha"], when
        return None

    def post_comment(self, owner: str, repo: str, number: int, body: str) -> str:
        """Comment on a pull request (both forges file PR comments as issue comments).
        Needs a token with write access: GitHub `Pull requests: write` (fine-grained) or
        `public_repo`/`repo` (classic); Forgejo `write:issue`. Returns the comment URL."""
        r = self.http.post(f"{self.api}/repos/{quote(owner)}/{quote(repo)}/issues/{number}/comments",
                           json={"body": body})
        if r.status_code in (401, 403, 404):
            raise SourceError(f"{self.host} refused the comment ({r.status_code}); the token needs "
                              "write access to pull request comments")
        r.raise_for_status()
        return r.json().get("html_url") or ""

    def fetch(self, owner: str, repo: str, sha: str, path: str, max_bytes: int) -> bytes:
        p = quote(path)
        if self.provider == "github":
            url = f"{self.api}/repos/{quote(owner)}/{quote(repo)}/contents/{p}?ref={sha}"
            headers = {"Accept": "application/vnd.github.raw"}
        else:
            # /media/ serves Git LFS objects as their content (and other files as they are)
            url = f"{self.api}/repos/{quote(owner)}/{quote(repo)}/media/{p}?ref={sha}"
            headers = {}
        data = self._download(url, headers, path, max_bytes)
        if self.provider == "github" and data.startswith(LFS_POINTER):
            # the contents API hands back an LFS pointer; GitHub serves the object here
            data = self._download(f"https://media.githubusercontent.com/media/{quote(owner)}/"
                                  f"{quote(repo)}/{sha}/{p}", {}, path, max_bytes)
        return data

    def _download(self, url: str, headers: dict, path: str, max_bytes: int) -> bytes:
        with self.http.stream("GET", url, headers=headers) as r:
            if r.status_code >= 400:
                raise SourceError(f"could not download {path} ({r.status_code})")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    raise SourceError(f"{path} is larger than {max_bytes // 2**20} MB")
            return bytes(buf)

    def blob_url(self, owner: str, repo: str, sha: str, path: str) -> str:
        if self.provider == "github":
            return f"https://github.com/{owner}/{repo}/blob/{sha}/{quote(path)}"
        return f"{self.host}/{owner}/{repo}/src/commit/{sha}/{quote(path)}"
