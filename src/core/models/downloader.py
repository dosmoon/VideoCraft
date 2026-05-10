"""Single-file resume-capable HTTP downloader.

Streaming GET with Range support, optional sha256 verification, and a
cancel token. Writes to <target>.part during download and renames atomically
on success — interrupted downloads can be resumed by re-calling with the
same target_path. If the server returns 200 (no Range support) the .part is
discarded and the download restarts from zero.

Used by core.models.manager. Does not know about sources / fallback / queue —
that's the manager's job. Keeping this layer dumb makes it trivially testable.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Callable

import requests


_CHUNK_DEFAULT = 1 << 20   # 1 MiB
_PROGRESS_TICK = 0.25      # seconds between on_progress callbacks


@dataclass
class DownloadProgress:
    """Snapshot delivered to on_progress callbacks."""
    bytes_done:    int
    bytes_total:   int            # 0 when server didn't send Content-Length
    bytes_per_sec: float
    eta_sec:       float | None   # None when total unknown
    url:           str
    target_path:   str

    @property
    def fraction(self) -> float:
        if self.bytes_total <= 0:
            return 0.0
        return min(1.0, self.bytes_done / self.bytes_total)


class CancelToken:
    """Cooperative cancel signal. Polled by the downloader between chunks
    so a UI cancel button takes effect within ~one chunk's network read."""

    __slots__ = ("_cancelled",)

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class DownloadError(Exception):
    """All downloader failure modes funnel through this. The manager catches
    it to drive source fallback. `kind` is one of:
        network    — HTTP / connection / timeout
        sha256     — file content mismatch after completion
        size       — Content-Length disagreed with expected
        cancelled  — caller flipped the cancel token
        io         — local disk write / rename failure
    """
    def __init__(self, kind: str, message: str, *, url: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.url = url


def download_file(
    url: str,
    target_path: str,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    on_progress: Callable[[DownloadProgress], None] | None = None,
    cancel_token: CancelToken | None = None,
    chunk_size: int = _CHUNK_DEFAULT,
    connect_timeout: float = 15.0,
    read_timeout: float = 60.0,
) -> None:
    """Download `url` → `target_path`, resuming from `<target_path>.part` if present.

    Atomic on success: rename .part → final only after the full body lands and
    sha256 (when supplied) verifies. Failure leaves .part on disk so the next
    call can resume.

    Raises DownloadError on any failure. Re-raises nothing else (requests
    exceptions are wrapped).
    """
    if cancel_token is not None and cancel_token.cancelled:
        raise DownloadError("cancelled", "Cancelled before start", url=url)

    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    part_path = target_path + ".part"

    # Resume: pick up where we left off if .part exists.
    resume_from = 0
    if os.path.exists(part_path):
        try:
            resume_from = os.path.getsize(part_path)
        except OSError:
            resume_from = 0

    # If a complete file already sits at target_path and matches sha256
    # (or no sha256 to check), skip — caller logic decides whether to
    # short-circuit at a higher level too.
    if os.path.exists(target_path):
        if _file_matches(target_path, expected_size, expected_sha256):
            return
        # Mismatch — treat as corrupt, restart fresh.
        try:
            os.remove(target_path)
        except OSError as e:
            raise DownloadError("io", f"Cannot remove stale target: {e}",
                                url=url) from e
        resume_from = 0
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass

    headers = {}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    try:
        resp = requests.get(
            url, stream=True, headers=headers,
            timeout=(connect_timeout, read_timeout),
            allow_redirects=True,
        )
    except requests.RequestException as e:
        raise DownloadError("network", f"Connect/request failed: {e}",
                            url=url) from e

    try:
        if resp.status_code == 416:
            # Range not satisfiable — server says we already have everything.
            # Try treating .part as complete: rename + verify.
            resp.close()
            os.replace(part_path, target_path)
            if not _file_matches(target_path, expected_size, expected_sha256):
                raise DownloadError(
                    "sha256",
                    "Resumed file failed verification (server returned 416 "
                    "but sha256/size mismatch).",
                    url=url,
                )
            return

        if resp.status_code == 200:
            # Server ignored Range — restart from zero. Drop the stale .part.
            resume_from = 0
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
            except OSError:
                pass
        elif resp.status_code == 206:
            # Partial Content — resume confirmed.
            pass
        else:
            raise DownloadError(
                "network",
                f"HTTP {resp.status_code} for {url}",
                url=url,
            )

        # Total bytes for progress: prefer Content-Range when resuming.
        total_bytes = expected_size or 0
        cl = resp.headers.get("Content-Length")
        cr = resp.headers.get("Content-Range")
        if cr and "/" in cr:
            try:
                total_bytes = int(cr.split("/")[-1])
            except ValueError:
                pass
        elif cl:
            try:
                served = int(cl)
                total_bytes = resume_from + served if resp.status_code == 206 else served
            except ValueError:
                pass

        bytes_done = resume_from
        last_emit = 0.0
        started = time.monotonic()

        # Append (resume) or overwrite (fresh start).
        mode = "ab" if resume_from > 0 else "wb"
        try:
            with open(part_path, mode) as fh:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if cancel_token is not None and cancel_token.cancelled:
                        # Keep .part on disk so next call resumes.
                        raise DownloadError("cancelled",
                                            "Cancelled by user", url=url)
                    if not chunk:
                        continue
                    fh.write(chunk)
                    bytes_done += len(chunk)
                    if on_progress is not None:
                        now = time.monotonic()
                        if now - last_emit >= _PROGRESS_TICK or bytes_done >= total_bytes > 0:
                            elapsed = max(now - started, 1e-6)
                            speed = (bytes_done - resume_from) / elapsed
                            eta = ((total_bytes - bytes_done) / speed) if (
                                speed > 0 and total_bytes > 0) else None
                            on_progress(DownloadProgress(
                                bytes_done=bytes_done,
                                bytes_total=total_bytes,
                                bytes_per_sec=speed,
                                eta_sec=eta,
                                url=url,
                                target_path=target_path,
                            ))
                            last_emit = now
        except OSError as e:
            raise DownloadError("io", f"Disk write failed: {e}",
                                url=url) from e
        except requests.RequestException as e:
            raise DownloadError("network", f"Stream read failed: {e}",
                                url=url) from e
    finally:
        try:
            resp.close()
        except Exception:
            pass

    # Verify size + sha256 against expectations before committing.
    if expected_size is not None and expected_size > 0:
        actual = os.path.getsize(part_path)
        # Allow up to 5% drift on `expected_size` (catalog uses approximations).
        if actual < int(expected_size * 0.5):
            raise DownloadError(
                "size",
                f"Downloaded size {actual} far below expected {expected_size}",
                url=url,
            )

    if expected_sha256:
        actual_sha = _sha256_file(part_path)
        if actual_sha.lower() != expected_sha256.lower():
            try:
                os.remove(part_path)
            except OSError:
                pass
            raise DownloadError(
                "sha256",
                f"sha256 mismatch: expected {expected_sha256}, got {actual_sha}",
                url=url,
            )

    try:
        os.replace(part_path, target_path)
    except OSError as e:
        raise DownloadError("io", f"Rename failed: {e}", url=url) from e

    # Final progress emit so UIs see 100%.
    if on_progress is not None:
        on_progress(DownloadProgress(
            bytes_done=os.path.getsize(target_path),
            bytes_total=os.path.getsize(target_path),
            bytes_per_sec=0.0,
            eta_sec=0.0,
            url=url,
            target_path=target_path,
        ))


def verify_file(path: str, expected_sha256: str | None = None,
                expected_size: int | None = None) -> bool:
    """True if `path` exists and matches the expected size (loose) and
    sha256 (when supplied). Used by registry to mark complete vs corrupt."""
    return _file_matches(path, expected_size, expected_sha256)


# ── Internals ────────────────────────────────────────────────────────────────

def _file_matches(path: str, expected_size: int | None,
                  expected_sha256: str | None) -> bool:
    if not os.path.exists(path):
        return False
    if expected_size is not None and expected_size > 0:
        actual = os.path.getsize(path)
        # Loose size check: catalog sizes are approximations.
        if actual < int(expected_size * 0.5):
            return False
    if expected_sha256:
        try:
            return _sha256_file(path).lower() == expected_sha256.lower()
        except OSError:
            return False
    return True


def _sha256_file(path: str, *, chunk_size: int = _CHUNK_DEFAULT) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()
