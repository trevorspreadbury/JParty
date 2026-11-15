"""Main module."""

from jparty.app.bootstrap import main

if __name__ == "__main__":
    # Pass subcommand exit codes (for example ``self-check``) to the OS. The GUI
    # path returns ``None``, which exits with 0.
    raise SystemExit(main())
