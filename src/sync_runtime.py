"""Private state and bounded retry for the single-host authoritative writer.

No employee data, URLs or exception bodies are logged. State must be on the
same private volume for every invocation; a distributed deployment needs a
distributed lease before enabling more than one host.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
import random
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class SyncBlocked(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class PrivateState:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_mode & 0o077:
            raise SyncBlocked('STATE_DIRECTORY_NOT_PRIVATE')

    def read(self, name, default=None):
        path = self.root / name
        if path.is_symlink():
            raise SyncBlocked('STATE_SYMLINK')
        return json.loads(path.read_text()) if path.exists() else default

    def save(self, name, value, immutable=False):
        if Path(name).name != name:
            raise SyncBlocked('INVALID_STATE_KEY')
        data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        path = self.root / name
        if path.is_symlink():
            raise SyncBlocked('STATE_SYMLINK')
        if immutable and path.exists():
            if path.read_bytes() != data:
                raise SyncBlocked('IMMUTABLE_STAGE_CHANGED')
            return
        fd, tmp = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @contextmanager
    def lock(self):
        path = self.root / 'writer.lock'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SyncBlocked('ANOTHER_RUN_OWNS_LOCK') from None
            # Expiry is diagnostic; never steal an active OS lock at expiry.
            stream.write(json.dumps({'pid': os.getpid(), 'expires_at': time.time() + 3600}))
            stream.flush()
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def request(session, method, url, *, sleep=time.sleep, attempts=6, **kwargs):
    import requests
    for attempt in range(attempts):
        try:
            response = session.request(method, url, timeout=90, **kwargs)
        except (requests.Timeout, requests.ConnectionError):
            response = None
        if response is not None and response.status_code < 400:
            return response
        code = response.status_code if response is not None else 503
        if code not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
            raise SyncBlocked('REMOTE_HTTP_' + str(code))
        try:
            retry = float(response.headers.get('Retry-After', '0')) if response is not None else 0
        except ValueError:
            retry = 0
        sleep(min(30, max(retry, 2 ** attempt + random.random())))
    raise SyncBlocked('RETRY_EXHAUSTED')
