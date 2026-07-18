"""Canonical, persistent, cross-process per-pack single-writer lock.

Two review findings shaped this module. Both were real defects in the previous
implementation, and both are worth stating plainly so the design is not undone
later by someone who thinks it looks over-engineered.

FINDING 1 -- deleting the lock file permits POSIX split-brain.
    The previous release() unlinked the lock pathname. On POSIX that is unsafe
    even with an identity check on acquire:

        1. A unlocks (still holding its descriptor)
        2. B opens and locks the SAME inode, and its identity check passes,
           because the pathname still resolves to that inode
        3. A unlinks the pathname
        4. C creates a NEW file at the pathname and locks the new inode
        5. B and C both believe they exclusively own the pack

    No check on the acquire side closes that window, because B was correct at
    the moment it looked. The only fix is to never unlink. The lock file is
    therefore PERSISTENT: it is never removed on release, on failure, during
    recovery, or during cleanup. Its existence carries NO meaning. Ownership is
    represented solely by the live kernel lock.

FINDING 2 -- output-relative lock paths do not protect pack identity.
    A lock under <output parent>/.lock-<packId> let two processes with the same
    packId but different --output roots take DIFFERENT locks while still
    mutating the same id ledger. Lock identity must be a property of the pack,
    not of the invocation, so the path is canonical and independent of --output,
    --source, --ledger, the source format, the CWD and any temp directory.

Kernel primitives (standard library only):
    Windows -- msvcrt.locking(LK_NBLCK)
    POSIX   -- fcntl.flock(LOCK_EX | LOCK_NB)
Both are released automatically when the owning process exits or crashes, which
is the property no marker file can provide.
"""

import errno
import os

from .schema import IDENT_RE

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

# Canonical namespace, relative to the repository root. It sits inside the
# gitignored build area, so the persistent lock files are never committed.
LOCK_ROOT_PARTS = ("build", "content-packs", ".locks")
LOCK_SUFFIX = ".lock"


class LockBusy(Exception):
    """Another process already owns this pack's single-writer lock."""


class LockUnavailable(Exception):
    """No kernel locking primitive is available on this interpreter."""


class LockPathRejected(Exception):
    """The pack id does not resolve to a safe canonical lock path."""


def repo_root():
    """Repository root, derived from this module's trusted location.

    Deliberately NOT from the CWD, an argument, or an environment variable:
    the whole point of a canonical lock is that no invocation detail can move
    it. locking.py lives at <repo>/scripts/contentpack/locking.py.
    """
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def lock_root():
    return os.path.join(repo_root(), *LOCK_ROOT_PARTS)


def canonical_lock_path(pack_id):
    """The one lock path for a pack id. Same id in, same path out, always."""
    if not isinstance(pack_id, str) or not IDENT_RE.match(pack_id):
        raise LockPathRejected(
            "pack id %r is not a valid identifier; refusing to build a lock "
            "path from it" % (pack_id,))

    root = lock_root()
    candidate = os.path.join(root, pack_id + LOCK_SUFFIX)

    # Containment, defence in depth. IDENT_RE already excludes separators, dots
    # and '..', so this cannot currently fail -- which is exactly why it is
    # cheap to keep, and why it must not be removed if IDENT_RE ever loosens.
    real_root = os.path.realpath(root)
    real_candidate = os.path.realpath(candidate)
    if os.path.dirname(real_candidate) != real_root:
        raise LockPathRejected(
            "lock path for pack %r escapes the canonical lock root" % (pack_id,))
    return candidate


def _try_lock(fd):
    """Exclusive, non-blocking, kernel-backed. False when another owner exists."""
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


class PackLock(object):
    """Single-writer boundary for one pack id. Use as a context manager.

    The lock file is created on first use and then kept forever. An existing
    but unlocked file never blocks anything -- it is reused as-is.
    """

    def __init__(self, pack_id):
        self.pack_id = pack_id
        self.path = canonical_lock_path(pack_id)
        self._fd = None

    def acquire(self):
        parent = os.path.dirname(self.path)
        if not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        # O_CREAT without O_EXCL: reusing an existing lock file is the normal,
        # expected case. The file is a rendezvous point, not a claim.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
        try:
            # msvcrt locks a byte range, so there must be a byte to lock. The
            # content is never read and carries no meaning.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            if not _try_lock(fd):
                os.close(fd)
                raise LockBusy(
                    "another process is building or recovering pack '%s'"
                    % self.pack_id)
        except LockBusy:
            raise
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        self._fd = fd
        return self

    def release(self):
        """Unlock and close. NEVER unlink -- see FINDING 1 in the module docstring."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        _unlock(fd)
        try:
            os.close(fd)
        except OSError:
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
