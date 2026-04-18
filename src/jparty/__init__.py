from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("jparty")
    except PackageNotFoundError:
        return "2.0.2"


__version__ = get_version()
