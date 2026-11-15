"""Single source of truth for the JParty version.

``pyproject.toml`` reads this value at build time (``[tool.setuptools.dynamic]``)
and ``jparty.__version__`` re-exports it, so bump the version here only.
"""

__version__ = "3.0.0"
