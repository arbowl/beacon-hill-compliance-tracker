"""ingest_client.py - FIXED VERSION
A small, importable client for uploading either a cache.json (how it was found)
or a basic/report JSON (what was found) to a receiver API.

Usage:

    from ingest_client import IngestClient, detect_kind, infer_committee_id

    client = IngestClient(
        base_url="http://172.17.43.95:5000/",
        signing_key_id="",
        signing_key_secret="",
    )

    # 1) Let the client auto-detect from filename + content
    client.upload_file("/path/to/cache.json")                # -> POST /ingest (no committee_id)
    client.upload_file("/path/to/basic_J14.json")           # -> POST /ingest?committee_id=J14

    # 2) Or force the type and/or committee id
    client.upload_file("/path/to/foo.json", kind="cache")  # -> POST /ingest
    client.upload_file("/path/to/foo.json", kind="basic", committee_id="J14")  # -> POST /ingest?committee_id=J14

Notes:
- 'basic' uploads expect a list of items. The client sends them directly as JSON array.
- committee_id can be inferred from filenames like 'basic_J14.json' or 'basic-J14-2025.json'.
- You can batch large 'basic' lists with batch_size.
"""
from __future__ import annotations

import json
import os
import time
import hashlib
import hmac
import re
from typing import Any, Optional, Literal

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


def detect_kind(path: str) -> str:
    """Detect 'cache' or 'basic' by filename and/or JSON shape.

    Heuristics:
    - filename contains 'cache' -> cache
    - filename startswith 'basic' or contains 'basic_' -> basic
    Raises ValueError if undecidable.
    """
    name = os.path.basename(path).lower()
    if "cache" in name:
        return "cache"
    if name.startswith("basic") or "basic_" in name or "report" in name:
        return "basic"
    raise ValueError("Report type not recognized.")


def infer_committee_id(path: str) -> Optional[str]:
    """Best-effort extraction from filenames like:
       basic_J14.json.
    Returns None if not found.
    """
    name = os.path.basename(path)
    # Try common patterns
    m = re.search(r"(?:basic|report)[-_]?([A-Za-z0-9]+)\b", name, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _make_session(timeout: int, max_retries: int) -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.request = _wrap_timeout(s.request, timeout)
    return s


def _wrap_timeout(fn, timeout: int):
    def _inner(method, url, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout
        return fn(method, url, **kwargs)
    return _inner


def _safe_json(resp: requests.Response) -> dict[str, Any]:
    try:
        return {"ok": resp.ok, "status": resp.status_code, "body": resp.json()}
    except Exception:
        return {"ok": resp.ok, "status": resp.status_code, "text": resp.text[:2000]}


def _chunked(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i:i+size] for i in range(0, len(seq), size)]


class IngestClient:
    def __init__(
        self,
        base_url: str,
        extra_headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
        retries: int = 3,
        signing_key_id: Optional[str] = None,
        signing_key_secret: Optional[str] = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self.session = _make_session(timeout=timeout, max_retries=retries)
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        if extra_headers:
            self.headers.update(extra_headers)
        self.signing_key_id = signing_key_id
        self.signing_key_secret = signing_key_secret

    def _signed_headers(self, method: str, path: str, body: dict) -> dict[str, str]:
        if not (self.signing_key_id and self.signing_key_secret):
            return {}
        ts = str(int(time.time()))
        body_hash = hashlib.sha256(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        msg = f"{ts}.{method.upper()}.{path}.{body_hash}".encode("utf-8")
        sig = hmac.new(self.signing_key_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return {
            "X-Ingest-Key-Id": self.signing_key_id,
            "X-Ingest-Timestamp": ts,
            "X-Ingest-Signature": sig,
        }

    def upload_file(
        self,
        path: str,
        kind: Optional[Literal["cache", "basic"]] = None,
        committee_id: Optional[str] = None,
        run_id: Optional[str] = None,
        batch_size: int = 0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Upload a cache or basic/report JSON to the receiver.

        Args:
            path: Path to JSON file.
            kind: 'cache' or 'basic'. If omitted, we try to detect from filename and content.
            committee_id: Required for 'basic' (inferred from filename if possible).
            run_id: Optional run id; defaults to current UTC timestamp for 'basic'.
            batch_size: If >0 and kind == 'basic', split items into batches of this size.
            dry_run: If True, do not send HTTP requests; return the would-be payload(s).

        Returns:
            A dict with 'endpoint' and 'results' (list per batch or single).
        """
        if not os.path.exists(path):
            print(f"File not found: {path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        kind = kind or detect_kind(path)

        if kind == "cache":
            return self._upload_cache(payload, dry_run=dry_run)

        if kind == "basic":
            # items array may be the file itself or wrapped as {items:[...]}
            items = payload if isinstance(payload, list) else payload.get("items", [])
            if not isinstance(items, list):
                raise ValueError("Expected a list of items for basic/report uploads.")

            cid = committee_id or infer_committee_id(path)
            if not cid:
                raise ValueError("committee_id is required for basic/report uploads and could not be inferred from filename.")

            rid = run_id or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return self._upload_basic(cid, items, rid, batch_size=batch_size, dry_run=dry_run)

        raise ValueError(f"Unsupported kind: {kind}")

    # --- Internals ---

    def _upload_cache(self, cache_payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        # FIXED: Use /ingest endpoint without committee_id parameter
        path = "/ingest"
        url = self.base_url + path
        extra = self._signed_headers("POST", path, cache_payload)
        headers = {**self.headers, **extra}
        if dry_run:
            return {
                "endpoint": url,
                "results": [{"status": 0, "dry_run": True, "payload_preview": json.dumps(cache_payload)[:4000]}],
            }
        resp = self.session.post(url, json=cache_payload, headers=headers)
        return {"endpoint": url, "results": [_safe_json(resp)]}

    def _upload_basic(
        self,
        committee_id: str,
        items: list[dict[str, Any]],
        run_id: str,
        batch_size: int = 0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        path = "/ingest/basic"
        url = self.base_url + path
        extra = self._signed_headers("POST", path, items)
        headers = {**self.headers, **extra}
        results: list[dict[str, Any]] = []
        batches = _chunked(items, batch_size) if batch_size and batch_size > 0 else [items]
        for idx, batch in enumerate(batches, start=1):
            body = {"committee_id": committee_id, "run_id": run_id, "items": batch}
            if dry_run:
                results.append({"status": 0, "batch": idx, "dry_run": True, "payload_preview": json.dumps(body)[:4000]})
                continue
            resp = self.session.post(url, json=body, headers=headers)
            results.append(_safe_json(resp))

        return {"endpoint": url, "results": results}

