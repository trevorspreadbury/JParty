"""Jparty package."""

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Run get version."""
    try:
        return version("jparty")
    except PackageNotFoundError:
        return "3.0.0"


__version__ = get_version()
