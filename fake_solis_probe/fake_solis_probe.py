#!/usr/bin/env python3
"""Launch Fake Solis Probe.

The implementation lives in the :mod:`solis_probe` package so each runtime
concern can be maintained and tested independently.
"""

from solis_probe.app import main

if __name__ == "__main__":
    raise SystemExit(main())
