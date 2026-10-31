"""Where designs come from: GitHub and Forgejo accounts, repos, folders and files.

Discovery uses each forge's git-tree API, so nothing is cloned: a scan lists the
`.sc` / `.solidcraft` files with their blob SHAs (cheap change detection), and a
render fetches just the one design file at the scanned commit.
"""

import fnmatch
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx

from .config import get_settings

DESIGN_SUFFIXES = (".sc", ".solidcraft")
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

    @property
    def canonical_url(self) -> str:
        url = f"{self.host}/{self.owner}"
        if self.repo:
            url += f"/{self.repo}"
            if self.ref or self.path:
                verb = "tree" if self.provider == "github" else "src/branch"
                url += f"/{verb}/{self.ref or 'HEAD'}"
                if self.path:
                    url += f"/{self.path}"
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
    host maps to the configured Forgejo web URL.
    """
    raw = raw.strip()
    if not raw:
        raise SourceError("empty source URL")
    forgejo = get_settings().forgejo_url.rstrip("/")

    # git@host:owner/repo.git (scp-like SSH)
    m = re.match(r"^[\w.-]+@([\w.-]+):(?!\d+/)(.+)$", raw)
    if m:
        host, path = m.groups()
        provider, base = ("github", "https://github.com") if host == "github.com" else ("forgejo", forgejo)
        return _from_path(provider, base, path)
    if re.match(r"^[\w.-]+/[\w.-]+$", raw):
        return _from_path("github", "https://github.com", raw)
    if "://" not in raw:
        raw = "https://" + raw

    parts = urlsplit(raw)
    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise SourceError(f"not a URL: {raw}")
    if hostname in ("github.com", "www.github.com"):
        return _from_path("github", "https://github.com", parts.path)
    if parts.scheme == "ssh":
        return _from_path("forgejo", forgejo, parts.path)
    base = f"{parts.scheme}://{parts.netloc.split('@')[-1]}"
    return _from_path("forgejo", base, parts.path)


def _from_path(provider: str, base: str, path: str) -> SourceSpec:
    segs = [s for s in path.strip("/").split("/") if s]
    if not segs:
        raise SourceError("the URL names no account or repository")
    owner = segs[0]
    if len(segs) == 1:
        return SourceSpec(provider, base, "account", owner)
    repo = segs[1].removesuffix(".git")
    rest = segs[2:]
    ref = path_in_repo = None
    if rest:
        # github: blob|tree/<ref>/<path>;  forgejo: src|raw/branch|commit|tag/<ref>/<path>
        if rest[0] in ("blob", "tree", "raw") and provider == "github" and len(rest) >= 2:
            ref, tail = rest[1], rest[2:]
        elif rest[0] in ("src", "raw", "media") and len(rest) >= 3 and rest[1] in ("branch", "commit", "tag"):
            ref, tail = rest[2], rest[3:]
        else:
            raise SourceError(f"don't know how to read {'/'.join(rest)} in a repository URL")
        path_in_repo = "/".join(tail) or None
    return SourceSpec(provider, base, "repo", owner, repo, ref, path_in_repo)


def is_design_path(path: str) -> bool:
    return path.lower().endswith(DESIGN_SUFFIXES)


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


def looks_like_design(data: bytes) -> bool:
    """`.sc` is also SuperCollider's extension: insist on SolidCraft's own header."""
    if data[:2] == b"PK":  # packaged design (zip)
        return True
    head = data[:512].lstrip()
    return head.startswith(b"{") and b'"solidcraft/' in head


class Forge:
    """The handful of forge API calls a scan and a render need."""

    def __init__(self, spec_provider: str, host: str, client: httpx.Client | None = None):
        self.provider = spec_provider
        self.host = host.rstrip("/")
        settings = get_settings()
        headers = {"User-Agent": "look-askew"}
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
        """A branch, tag or SHA → the commit SHA."""
        if SHA_RE.match(ref):
            return ref
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

    def fetch(self, owner: str, repo: str, sha: str, path: str, max_bytes: int) -> bytes:
        p = quote(path)
        if self.provider == "github":
            url = f"{self.api}/repos/{quote(owner)}/{quote(repo)}/contents/{p}?ref={sha}"
            headers = {"Accept": "application/vnd.github.raw"}
        else:
            url = f"{self.api}/repos/{quote(owner)}/{quote(repo)}/media/{p}?ref={sha}"
            headers = {}
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
