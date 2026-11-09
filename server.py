#!/usr/bin/env python3
"""Repo-local launcher for the package entry point.

Installed clients should run ``microwind-mcp`` instead of this file.
"""

from microwind.server_app import main

if __name__ == "__main__":
    raise SystemExit(main())
