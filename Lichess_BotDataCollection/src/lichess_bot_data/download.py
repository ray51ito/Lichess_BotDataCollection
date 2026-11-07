"""Resumable, parallel HTTP range downloader for large Lichess database dumps."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

_HTTP_PARTIAL_CONTENT = 206
_HTTP_TOO_MANY_REQUESTS = 429
_FSCTL_SET_SPARSE = 0x900C4


def make_sparse(path: Path) -> bool:
    """Marks a file as sparse on Windows/NTFS so presizing it does not zero-fill the disk.

    Without this, ``truncate`` to the full size writes the whole file once with zeros,
    which takes many minutes on a hard disk. Returns whether the flag was set.

    Args:
        path: Existing file to mark.
    """
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    generic_rw, share_rw, open_existing = 0xC0000000, 0x3, 3
    handle = kernel32.CreateFileW(str(path), generic_rw, share_rw, None, open_existing, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return False
    try:
        returned = ctypes.c_ulong(0)
        ok = kernel32.DeviceIoControl(
            ctypes.c_void_p(handle),
            _FSCTL_SET_SPARSE,
            None,
            0,
            None,
            0,
            ctypes.byref(returned),
            None,
        )
        return bool(ok)
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


@dataclass
class DownloadPlan:
    """Byte ranges of a remote file and which of them are already on disk.

    Attributes:
        url: Remote file URL.
        total_size: Remote file size in bytes.
        chunk_size: Size of each ranged request in bytes.
        done: Indices of chunks already written to disk.
    """

    url: str
    total_size: int
    chunk_size: int
    done: set[int] = field(default_factory=set)

    @property
    def n_chunks(self) -> int:
        """Number of chunks covering the whole file."""
        return (self.total_size + self.chunk_size - 1) // self.chunk_size

    def chunk_range(self, index: int) -> tuple[int, int]:
        """Returns the inclusive byte range [start, end] of a chunk."""
        start = index * self.chunk_size
        return start, min(start + self.chunk_size, self.total_size) - 1

    def pending(self) -> list[int]:
        """Returns chunk indices that still need downloading, in file order."""
        return [i for i in range(self.n_chunks) if i not in self.done]

    def rechunked(self, chunk_size: int) -> DownloadPlan:
        """Returns the same progress expressed in smaller chunks (``chunk_size`` must divide).

        Plans whose chunk size is not a multiple of ``chunk_size`` are returned unchanged.
        """
        if chunk_size >= self.chunk_size or self.chunk_size % chunk_size:
            return self
        k = self.chunk_size // chunk_size
        plan = DownloadPlan(self.url, self.total_size, chunk_size)
        plan.done = {i * k + j for i in self.done for j in range(k)} & set(range(plan.n_chunks))
        return plan


class RangeDownloader:
    """Downloads one file with several concurrent HTTP range requests.

    Progress is persisted in a sidecar ``<target>.progress.json`` so that an
    interrupted download resumes where it stopped.
    """

    def __init__(
        self,
        url: str,
        target: Path,
        n_workers: int = 4,
        chunk_size: int = 16 * 1024 * 1024,
        max_mb_s: float | None = None,
    ) -> None:
        """Prepares a download.

        Args:
            url: Remote file URL (must support HTTP range requests).
            target: Local path to write.
            n_workers: Number of concurrent connections.
            chunk_size: Bytes per ranged request (small chunks lose little when the server
                drops a connection mid-transfer).
            max_mb_s: Cap on the total download rate in MB/s (None: no cap), to leave
                bandwidth for other work on the same network.
        """
        self._url = url
        self._target = target
        self._progress_path = target.with_suffix(target.suffix + ".progress.json")
        self._n_workers = n_workers
        self._chunk_size = chunk_size
        self._max_bytes_s = max_mb_s * 1e6 if max_mb_s else None
        self._lock = threading.Lock()
        self._received = 0
        self._started = time.time()

    def run(self) -> Path:
        """Downloads all missing chunks and returns the completed file path."""
        plan = self._load_or_create_plan()
        queue = plan.pending()
        print(f"{len(queue)}/{plan.n_chunks} chunks to download -> {self._target}")
        started = self._started = time.time()
        threads = [
            threading.Thread(target=self._worker, args=(plan, queue, started), daemon=True)
            for _ in range(self._n_workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if plan.pending():
            raise RuntimeError("download finished with missing chunks; rerun to resume")
        self._progress_path.unlink(missing_ok=True)
        return self._target

    def _load_or_create_plan(self) -> DownloadPlan:
        if self._progress_path.exists() and self._target.exists():
            saved = json.loads(self._progress_path.read_text(encoding="utf-8"))
            plan = DownloadPlan(
                saved["url"], saved["total_size"], saved["chunk_size"], set(saved["done"])
            ).rechunked(self._chunk_size)
            self._save_plan(plan)
            return plan
        head = httpx.head(self._url, follow_redirects=True, timeout=60)
        head.raise_for_status()
        total = int(head.headers["content-length"])
        self._target.parent.mkdir(parents=True, exist_ok=True)
        self._target.write_bytes(b"")
        make_sparse(self._target)
        # one byte at the end sizes the file; truncate() would write zeros on Windows
        with self._target.open("r+b") as fh:
            fh.seek(total - 1)
            fh.write(b"\0")
        plan = DownloadPlan(self._url, total, self._chunk_size)
        self._save_plan(plan)
        return plan

    def _save_plan(self, plan: DownloadPlan) -> None:
        payload = {
            "url": plan.url,
            "total_size": plan.total_size,
            "chunk_size": plan.chunk_size,
            "done": sorted(plan.done),
        }
        # replace atomically so a power loss never leaves a truncated progress file
        tmp = self._progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self._progress_path)

    def _worker(self, plan: DownloadPlan, queue: list[int], started: float) -> None:
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            while True:
                with self._lock:
                    if not queue:
                        return
                    index = queue.pop(0)
                self._fetch_chunk_with_retry(client, plan, index)
                with self._lock:
                    plan.done.add(index)
                    self._save_plan(plan)
                    rate = self._received / max(time.time() - started, 1e-9) / 1e6
                    print(f"chunk {index} ok ({len(plan.done)}/{plan.n_chunks}, ~{rate:.1f} MB/s)")

    def _fetch_chunk_with_retry(self, client: httpx.Client, plan: DownloadPlan, index: int) -> None:
        start, end = plan.chunk_range(index)
        expected = end - start + 1
        for attempt in range(20):
            try:
                data = self._fetch_range(client, start, end)
                if len(data) == expected:
                    with self._target.open("r+b") as fh:
                        fh.seek(start)
                        fh.write(data)
                        # on disk before the chunk is marked done, so a power loss cannot skip it
                        fh.flush()
                        os.fsync(fh.fileno())
                    return
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"chunk {index} attempt {attempt}: {exc}")
            time.sleep(min(60.0, 5.0 * (attempt + 1)))
        raise RuntimeError(f"chunk {index} failed repeatedly")

    def _fetch_range(self, client: httpx.Client, start: int, end: int) -> bytes:
        parts: list[bytes] = []
        with client.stream("GET", self._url, headers={"Range": f"bytes={start}-{end}"}) as resp:
            if resp.status_code == _HTTP_TOO_MANY_REQUESTS:
                raise RuntimeError("rate limited (429)")
            if resp.status_code != _HTTP_PARTIAL_CONTENT:
                raise RuntimeError(f"unexpected status {resp.status_code}")
            for piece in resp.iter_bytes(1 << 16):
                parts.append(piece)
                self._throttle(len(piece))
        return b"".join(parts)

    def _throttle(self, n_bytes: int) -> None:
        # all connections share one budget: sleep while the run is ahead of the cap
        with self._lock:
            self._received += n_bytes
            received = self._received
        if self._max_bytes_s is not None:
            ahead = received / self._max_bytes_s - (time.time() - self._started)
            if ahead > 0:
                time.sleep(ahead)
