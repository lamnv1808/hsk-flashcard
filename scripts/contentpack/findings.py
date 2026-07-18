"""Finding accumulation with three separated severity classes.

The existing HSK importer has only "fatal" and "invisible": the first problem
aborts and everything else is silent. This module is the replacement contract.

Severity classes:
    FATAL           - abort, nonzero exit, no output changed.
    LAUNCH_BLOCKING - structurally buildable; QA sets launchEligible=false.
    WARNING / INFO  - recorded; never blocks the technical build.

Every finding carries a stable machine-readable code plus, where applicable,
a sourceKey and a source coordinate (Excel: sheet + cell/row; CSV: file + line
+ column). Findings accumulate; the build reports all of them, not just the
first, except where continuing would be unsafe.
"""

FATAL = "FATAL"
LAUNCH_BLOCKING = "LAUNCH_BLOCKING"
WARNING = "WARNING"
INFO = "INFO"

_SEVERITY_ORDER = {FATAL: 0, LAUNCH_BLOCKING: 1, WARNING: 2, INFO: 3}


def ascii_safe(value):
    """Render any string ASCII-only for console output.

    CLI output must be ASCII so a Windows cp1252 console cannot crash the
    build (the existing release helper is held to the same rule). Non-ASCII
    content still reaches the UTF-8 QA report files unmodified.
    """
    if value is None:
        return ""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


class Finding(object):
    """One validation result. Immutable by convention."""

    __slots__ = ("code", "severity", "message", "source", "coord", "source_key", "detail")

    def __init__(self, code, severity, message, source=None, coord=None,
                 source_key=None, detail=None):
        if severity not in _SEVERITY_ORDER:
            raise ValueError("unknown severity: %r" % (severity,))
        self.code = code
        self.severity = severity
        self.message = message
        self.source = source          # sheet name, or csv file name
        self.coord = coord            # "B12" / "row 12" / "line 12 col 3"
        self.source_key = source_key
        self.detail = detail          # optional dict, QA report only

    def location(self):
        parts = []
        if self.source:
            parts.append(str(self.source))
        if self.coord:
            parts.append(str(self.coord))
        return "!".join(parts) if parts else ""

    def to_dict(self):
        out = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.source is not None:
            out["source"] = self.source
        if self.coord is not None:
            out["coord"] = self.coord
        if self.source_key is not None:
            out["sourceKey"] = self.source_key
        if self.detail is not None:
            out["detail"] = self.detail
        return out

    def to_line(self):
        """One ASCII-safe console line. Never includes raw learner content."""
        loc = self.location()
        head = "%-15s %s" % (self.severity, self.code)
        if loc:
            head += " at " + ascii_safe(loc)
        if self.source_key:
            head += " [" + ascii_safe(self.source_key) + "]"
        return head + ": " + ascii_safe(self.message)

    def sort_key(self):
        return (
            _SEVERITY_ORDER[self.severity],
            self.code,
            self.source or "",
            self.coord or "",
            self.source_key or "",
            self.message,
        )


class Findings(object):
    """Ordered accumulator. Deterministic when sorted for reporting."""

    def __init__(self):
        self._items = []

    def add(self, code, severity, message, source=None, coord=None,
            source_key=None, detail=None):
        self._items.append(Finding(code, severity, message, source, coord,
                                   source_key, detail))

    def fatal(self, code, message, **kw):
        self.add(code, FATAL, message, **kw)

    def launch_blocking(self, code, message, **kw):
        self.add(code, LAUNCH_BLOCKING, message, **kw)

    def warning(self, code, message, **kw):
        self.add(code, WARNING, message, **kw)

    def info(self, code, message, **kw):
        self.add(code, INFO, message, **kw)

    def extend(self, other):
        if isinstance(other, Findings):
            self._items.extend(other._items)
        else:
            self._items.extend(other)

    def of_severity(self, severity):
        return [f for f in self._items if f.severity == severity]

    def without_codes(self, excluded):
        """A copy with the given codes removed.

        Used to keep build-event notices (which depend on how the build was
        invoked) out of the QA report, which describes the pack rather than the
        invocation. Without this, an immediately following --check would report
        drift for a reason that has nothing to do with the content.
        """
        clone = Findings()
        clone._items = [f for f in self._items if f.code not in excluded]
        return clone

    def has_fatal(self):
        return any(f.severity == FATAL for f in self._items)

    def has_launch_blocking(self):
        return any(f.severity == LAUNCH_BLOCKING for f in self._items)

    def sorted_items(self):
        """Deterministic ordering, so QA reports are byte-stable."""
        return sorted(self._items, key=lambda f: f.sort_key())

    def to_list(self):
        return [f.to_dict() for f in self.sorted_items()]

    def counts(self):
        out = {FATAL: 0, LAUNCH_BLOCKING: 0, WARNING: 0, INFO: 0}
        for f in self._items:
            out[f.severity] += 1
        return out

    def codes(self):
        return sorted({f.code for f in self._items})

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class FatalError(Exception):
    """Raised to abort a build. Carries the accumulated findings."""

    def __init__(self, findings, message="build aborted"):
        Exception.__init__(self, message)
        self.findings = findings
