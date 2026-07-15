#!/usr/bin/env python3
"""Fixed entry point for the privileged-review-approved Aviato build."""

from aviato.plugins.approved_release import main

if __name__ == "__main__":
    raise SystemExit(main())
