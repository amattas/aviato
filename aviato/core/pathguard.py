from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import PathConfinementError


def _reject(relative: str, operation: str) -> PathConfinementError:
    return PathConfinementError(f"cannot {operation} {relative!r}: path is not confined to its root")


def confined_target(root: Path, relative: str, *, operation: str) -> Path:
    """Return a root-confined target for one relative filesystem operation.

    The caller supplies the trusted root separately from untrusted relative data.
    Existing symlinks are rejected component-by-component, including a symlink at
    the leaf, so callers never follow one while probing metadata or content.
    """
    pure = PurePosixPath(relative)
    if (
        not relative
        or relative == "."
        or pure.is_absolute()
        or PureWindowsPath(relative).is_absolute()
        or relative.startswith("\\")
        or ".." in pure.parts
    ):
        raise _reject(relative, operation)
    try:
        confined_root = Path(root).resolve(strict=False)
        target = confined_root.joinpath(*pure.parts)
        candidate = confined_root
        for part in pure.parts:
            candidate /= part
            if candidate.is_symlink():
                raise _reject(relative, operation)
            if candidate.exists() and not candidate.resolve(strict=True).is_relative_to(confined_root):
                raise _reject(relative, operation)
        if not target.parent.resolve(strict=False).is_relative_to(confined_root):
            raise _reject(relative, operation)
    except PathConfinementError:
        raise
    except OSError as exc:
        raise _reject(relative, operation) from exc
    return target
