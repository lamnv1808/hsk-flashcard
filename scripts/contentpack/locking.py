"""Cross-process, per-pack single-writer lock.

A journal-presence check is not a lock. Two builders can both read the journal
path, both see nothing, both read the same ledger, both allocate the same ids,
both write into the same staging directory, and then race to create the journal
-- with the loser's staged bytes published under the winner's transaction. This
module closes that window.

Design constraints and the reasoning behind each:

  - Kernel-backed, never advisory-by-convention. Ownership comes from a byte
    range lock held by the OS on an open handle: msvcrt.locking on Windows,
    fcntl.flock on POSIX. Both are released automatically when the process
    exits or crashes, which is precisely the property a stale marker file
    cannot provide.

  - Existence is never ownership. The lock FILE may legitimately exist while
    nobody holds it, so this module never infers ownership from the path and
    never deletes a lock because it "looks old". A competitor is detected only
    by the kernel refusing the lock.

  - Per pack. The path is <packId>-scoped, so different packs never contend.

  - Non-blocking. A competitor fails fast and loudly rather than queueing, so
    CI surfaces contention instead of hiding it behind a timeout.

  - Standard library only.
"""

import errno
import os

if os.name == "nt":                                    # pragma: no cover
    import msvcrt
    _HAVE_MSVCRT = True
    _HAVE_FCNTL = False
else:                                                  # pragma: no cover
    try:
        import fcntl
        _HAVE_FCNTL = True
    except ImportError:
        _HAVE_FCNTL = False
    _HAVE_MSVCRT = False

# Bounded retry for the unlink race described in _acquire_fd.
_IDENTITY_RETRIES = 5


class LockBusy(Exception):
    """Another process already owns this pack's single-writer lock."""


class LockUnavailable(Exception):
    """No kernel locking primitive is available on this interpreter."""


def lock_path(output_dir, pack_id):
    """Beside the pack directory, on the artifact volume."""
    parent = os.path.dirname(os.path.abspath(output_dir))
    return os.path.join(parent, ".lock-%s" % pack_id)


def _try_lock(fd):
    """Take an exclusive, non-blocking byte-range lock. False when contended."""
    if _HAVE_MSVCRT:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                return False
            raise
    if _HAVE_FCNTL:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                return False
            raise
    raise LockUnavailable(
        "no kernel file-locking primitive is available; refusing to run "
        "without a single-writer guarantee")


def _unlock(fd):
    if _HAVE_MSVCRT:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    elif _HAVE_FCNTL:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


def _same_file(fd, path):
    """True when the locked handle still refers to the live lock path.

    Closes the classic unlink race: if the owner deletes the lock file between
    our open() and our lock(), we could end up holding a lock on an orphaned
    inode while a third process locks a freshly created one. Comparing the
    handle's identity against the path's catches that.
    """
    try:
        a = os.fstat(fd)
        b = os.stat(path)
    except OSError:
        return False
    return (a.st_ino, a.st_dev) == (b.st_ino, b.st_dev)


class PackLock(object):
    """Single-writer boundary for one pack. Use as a context manager."""

    def __init__(self, output_dir, pack_id):
        self.path = lock_path(output_dir, pack_id)
        self.pack_id = pack_id
        self._fd = None

    def acquire(self):
        parent = os.path.dirname(self.path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

        last = None
        for _ in range(_IDENTITY_RETRIES):
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
            try:
                # msvcrt locks a byte range, so the file needs at least one
                # byte to lock. The content is irrelevant and never read.
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                if not _try_lock(fd):
                    os.close(fd)
                    raise LockBusy(
                        "another process is building or recovering pack '%s'"
                        % self.pack_id)
                if _same_file(fd, self.path):
                    self._fd = fd
                    return self
                # The file was replaced under us; drop it and try again.
                _unlock(fd)
                os.close(fd)
                last = "lock file was replaced during acquisition"
            except LockBusy:
                raise
            except OSError:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
        raise LockBusy(
            "could not obtain a stable lock for pack '%s' (%s)"
            % (self.pack_id, last))

    def release(self):
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        _unlock(fd)
        try:
            os.close(fd)
        except OSError:
            pass
        # Unlink only after closing: Windows refuses to delete a file that any
        # handle -- including our own -- still holds open. The window this
        # opens (a competitor locking the inode we just unlinked) is closed on
        # the acquire side by _same_file(), which rejects a handle that no
        # longer refers to the live path.
        try:
            os.remove(self.path)
        except OSError:
            # A competitor already has it open, or the platform refuses. Both
            # are harmless: the file carries no state, and ownership is never
            # inferred from its existence.
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
