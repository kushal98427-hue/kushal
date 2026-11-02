"""Download company-wise CSVs from the source repository with caching and retries.

Strategy (most to least efficient):

1. Ask the GitHub API for the repository tree once. It returns every CSV path
   plus its git *blob SHA*. If our cached file has the same blob SHA, nothing is
   downloaded.
2. Download changed files from ``raw.githubusercontent.com`` using an ETag
   (``If-None-Match``) so unchanged files return ``304 Not Modified``.
3. If the tree API is unavailable, fall back to the symbol list in
   ``config/sector_map.csv``.

Every failure is logged per ticker; one bad ticker never aborts the scan. Source
data is only ever *read*: we write to our own cache directory, never to the
source repository.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nepse_ta.config import EXPECTED_COLUMNS, SOURCE_BRANCH, SOURCE_CSV_DIR, SOURCE_REPO

log = logging.getLogger(__name__)

RAW_BASE = f"https://raw.githubusercontent.com/{SOURCE_REPO}/{SOURCE_BRANCH}/{SOURCE_CSV_DIR}/"
TREE_URL = f"https://api.github.com/repos/{SOURCE_REPO}/git/trees/{SOURCE_BRANCH}?recursive=1"
COMMIT_URL = f"https://api.github.com/repos/{SOURCE_REPO}/commits/{SOURCE_BRANCH}"


@dataclass
class SourceInfo:
    """Where the data came from (for the report's provenance section)."""

    mode: str  # "github" or "local"
    commit_sha: str | None = None
    commit_date_utc: str | None = None
    listing: str = "unknown"  # "tree-api" | "sector-map-fallback" | "local-dir"


@dataclass
class FetchResult:
    """Outcome of a fetch run."""

    files: dict[str, Path] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    cache_warnings: dict[str, str] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=lambda: {"downloaded": 0, "not_modified": 0, "cache_hit": 0})
    source: SourceInfo = field(default_factory=lambda: SourceInfo(mode="github"))


def git_blob_sha(content: bytes) -> str:
    """Compute git's blob SHA-1 for ``content`` (identical to what the tree API reports)."""
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324 - git object id, not security


def make_session(retries: int = 4, backoff: float = 1.5) -> requests.Session:
    """HTTP session that retries transient failures (connection errors, 429, 5xx)."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = "nepse-ta-scanner/1.0"
    return session


def _api_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:  # never logged
        headers["Authorization"] = f"Bearer {token}"
    return headers


def list_remote_tree(session: requests.Session | None = None) -> tuple[dict[str, str], SourceInfo] | None:
    """Return ({symbol: blob_sha}, SourceInfo) from the GitHub API, or None if unavailable."""
    session = session or make_session()
    try:
        resp = session.get(TREE_URL, headers=_api_headers(), timeout=30)
        if resp.status_code != 200:
            log.warning("Tree API returned HTTP %s; falling back", resp.status_code)
            return None
        tree = resp.json()
        prefix = SOURCE_CSV_DIR + "/"
        symbols = {
            item["path"][len(prefix) : -4]: item["sha"]
            for item in tree.get("tree", [])
            if item.get("type") == "blob" and item["path"].startswith(prefix) and item["path"].endswith(".csv")
        }
        info = SourceInfo(mode="github", listing="tree-api")
        try:
            c = session.get(COMMIT_URL, headers=_api_headers(), timeout=30)
            if c.status_code == 200:
                cj = c.json()
                info.commit_sha = cj.get("sha")
                info.commit_date_utc = cj.get("commit", {}).get("committer", {}).get("date")
        except requests.RequestException as exc:  # provenance is nice-to-have
            log.warning("Could not read source commit info: %s", exc)
        return symbols, info
    except (requests.RequestException, ValueError) as exc:
        log.warning("Tree API unavailable (%s); falling back", exc)
        return None


def list_remote_symbols() -> list[str]:
    """Convenience: list of symbols from the tree API (empty list if unavailable)."""
    res = list_remote_tree()
    return sorted(res[0]) if res else []


def _looks_like_csv(content: bytes) -> bool:
    first = content.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip().lstrip("﻿")
    return first.split(",")[: len(EXPECTED_COLUMNS)] == list(EXPECTED_COLUMNS)


class CsvCache:
    """On-disk cache: ``<dir>/csv/<SYMBOL>.csv`` plus ``<dir>/meta.json``."""

    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir
        self.csv_dir = cache_dir / "csv"
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = cache_dir / "meta.json"
        try:
            self.meta: dict[str, dict] = json.loads(self.meta_path.read_text())
        except (FileNotFoundError, ValueError):
            self.meta = {}

    def path(self, symbol: str) -> Path:
        return self.csv_dir / f"{symbol}.csv"

    def blob_sha(self, symbol: str) -> str | None:
        p = self.path(symbol)
        return git_blob_sha(p.read_bytes()) if p.exists() else None

    def store(self, symbol: str, content: bytes, etag: str | None) -> None:
        tmp = self.path(symbol).with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(self.path(symbol))  # atomic: never leaves a half-written CSV
        self.meta[symbol] = {"etag": etag, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    def save_meta(self) -> None:
        self.meta_path.write_text(json.dumps(self.meta, indent=1, sort_keys=True))


def _fetch_one(
    session: requests.Session, cache: CsvCache, symbol: str, expected_sha: str | None
) -> tuple[str, str, Path | None, str | None]:
    """Fetch one symbol. Returns (symbol, outcome, path, error)."""
    path = cache.path(symbol)
    if expected_sha and path.exists() and cache.blob_sha(symbol) == expected_sha:
        return symbol, "cache_hit", path, None
    headers = {}
    etag = cache.meta.get(symbol, {}).get("etag")
    if etag and path.exists() and not expected_sha:
        headers["If-None-Match"] = etag
    try:
        resp = session.get(RAW_BASE + f"{symbol}.csv", headers=headers, timeout=60)
    except requests.RequestException as exc:
        return symbol, "error", path if path.exists() else None, f"network error: {exc}"
    if resp.status_code == 304 and path.exists():
        return symbol, "not_modified", path, None
    if resp.status_code != 200:
        return symbol, "error", path if path.exists() else None, f"HTTP {resp.status_code}"
    content = resp.content
    if not _looks_like_csv(content):
        return symbol, "error", path if path.exists() else None, "unexpected CSV header"
    if expected_sha and git_blob_sha(content) != expected_sha:
        # raw.githubusercontent is CDN-cached for a few minutes; accept but note it.
        log.info("%s: content differs from tree blob (CDN lag?)", symbol)
    cache.store(symbol, content, resp.headers.get("ETag"))
    return symbol, "downloaded", path, None


def fetch_from_github(
    cache_dir: Path,
    fallback_symbols: list[str],
    symbols: list[str] | None = None,
    workers: int = 8,
) -> FetchResult:
    """Download (or reuse cached) CSVs for all symbols in the source repo."""
    session = make_session()
    cache = CsvCache(cache_dir)
    result = FetchResult()
    tree = list_remote_tree(session)
    if tree:
        remote, result.source = tree
    else:
        remote = {s: None for s in fallback_symbols}
        result.source = SourceInfo(mode="github", listing="sector-map-fallback")
    wanted = sorted(set(symbols) & set(remote)) if symbols else sorted(remote)
    if symbols:
        for s in sorted(set(symbols) - set(remote)):
            result.failures[s] = "symbol not found in source repository"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch_one, session, cache, s, remote.get(s)) for s in wanted]
        for fut in as_completed(futures):
            sym, outcome, path, err = fut.result()
            if outcome == "error":
                if path is not None:
                    result.files[sym] = path
                    result.cache_warnings[sym] = f"download failed ({err}); using cached copy"
                    log.warning("%s: %s -- using cached copy", sym, err)
                else:
                    result.failures[sym] = err or "unknown error"
                    log.error("%s: download failed: %s", sym, err)
            else:
                result.stats[outcome] += 1
                result.files[sym] = path  # type: ignore[assignment]
    cache.save_meta()
    log.info("Fetch stats: %s, failures: %d", result.stats, len(result.failures))
    return result


def load_from_local_dir(directory: Path, symbols: list[str] | None = None) -> FetchResult:
    """Use an existing local clone (``.../data/company-wise``) instead of downloading."""
    result = FetchResult(source=SourceInfo(mode="local", listing="local-dir"))
    for p in sorted(directory.glob("*.csv")):
        if symbols and p.stem not in symbols:
            continue
        result.files[p.stem] = p
    if symbols:
        for s in sorted(set(symbols) - set(result.files)):
            result.failures[s] = "symbol not found in local directory"
    return result
