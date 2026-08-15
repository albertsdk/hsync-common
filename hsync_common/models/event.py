"""
Event model for HSYNC.

This module defines the Event class and EventName enum for representing
file system events (add, modify, rename, delete) that are synchronized
between client and server via WebSocket.
"""

from enum import StrEnum
from pathlib import Path
from re import compile as _re_compile
from typing import TYPE_CHECKING, TypedDict

from .dir import Dir
from .file import File
from .symlink import Symlink

if TYPE_CHECKING:
    from .file import FileDict

# Canonical shape of a client ID on the wire: strictly alphanumeric (ASCII
# letters and digits only, no separators), exactly 21 characters, so a cid
# always starts with a letter or digit — never ``-`` or ``_``. Applied to cid
# values received from remote peers (form fields, WS paths, event payloads)
# before trusting them for echo suppression or logging.
CID_PATTERN = r"^[A-Za-z0-9]{21}$"
_CID_RE = _re_compile(CID_PATTERN)


def is_valid_cid(value: object) -> bool:
    """Return True when *value* is a well-formed client ID (see CID_PATTERN).

    Uses ``fullmatch``: with ``$``-anchored ``match`` a trailing ``\\n`` would
    be accepted (Python's ``$`` also matches before a final newline), letting
    a cid smuggle forged lines into logs.
    """
    return isinstance(value, str) and bool(_CID_RE.fullmatch(value))


class EventDict(TypedDict):
    """Type-safe dictionary representation of an Event."""

    cid: str
    name: str
    bucket: str
    src: "FileDict | dict"
    dst: "FileDict | dict | None"


class EventName(StrEnum):
    """
    Enumeration of supported file system event types.

    Values:
        added: A new file or directory was created.
        modified: An existing file was modified.
        renamed: A file or directory was renamed/moved.
        deleted: A file or directory was deleted.
        symlink: A symbolic link was created or modified.
    """

    added = "added"
    modified = "modified"
    renamed = "renamed"
    deleted = "deleted"
    symlink = "symlink"


def _correct_path(
    entity: File | Dir | Symlink, localpath: Path | str, strip_localpath: bool
) -> None:
    """Normalize the path of a File, Dir, or Symlink entity.

    Stripping uses :meth:`pathlib.Path.relative_to` (component-aware),
    never a string prefix: a path that merely shares the leading
    characters of *localpath* (e.g. ``/base2/x`` vs ``/base``) is not
    inside it and must be kept verbatim instead of being mangled into
    a bogus relative path (``2/x``). The entity is rewritten in place:
    callers must not reuse the src/dst objects after construction.

    Promoted to a module-level helper (from a per-``Event`` closure) so the
    function object is created once per process instead of once per instance.
    """
    path = str(entity.path) if isinstance(entity, Dir) else str(entity.filepath)

    if strip_localpath:
        try:
            rel = str(Path(path).relative_to(localpath))
        except ValueError:
            # Not under localpath: keep the original path rather than
            # emitting a corrupted relative one.
            pass
        else:
            # relative_to of localpath itself yields "." — normalize
            # to "" so the bucket root stays an empty relative path.
            path = "" if rel == "." else rel
    else:
        path = str(Path(localpath) / path.lstrip("/"))

    if isinstance(entity, Dir):
        entity.path = path
    else:
        entity.filepath = path


class Event:
    """
    Represents a file system synchronization event.

    Events are broadcast via WebSocket to notify other clients about
    file system changes. Each event contains information about the
    source file/directory and optionally a destination (for renames).

    Attributes:
        cid: Client ID that originated the event.
        bucket: Name of the bucket where the event occurred.
        name: Type of event (added, modified, renamed, deleted).
        src: Source file or directory affected by the event.
        dst: Destination file or directory (for rename events).
    """

    def __init__(
        self,
        cid: str,
        localpath: str,
        bucket: str,
        name: EventName,
        src: File | Dir | Symlink,
        dst: File | Dir | Symlink | None = None,
        strip_localpath: bool = True,
    ):
        self.cid = cid
        self.bucket = bucket
        self.name = name.value

        # Path objects are parsed once per Event (was once per entity per call).
        lp = Path(localpath)

        _correct_path(src, lp, strip_localpath)
        self.src = src

        if dst is not None:
            _correct_path(dst, lp, strip_localpath)
        self.dst = dst

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"cid={self.cid}, "
            f"name={self.name}, "
            f"bucket={self.bucket}, "
            f"src={self.src}, "
            f"dst={self.dst})"
        )

    def to_dict(self) -> EventDict:
        """Convert the Event instance to an EventDict."""
        return EventDict(
            cid=self.cid,
            name=self.name,
            bucket=self.bucket,
            src=self.src.to_dict(),
            dst=self.dst.to_dict() if self.dst else None,
        )
