"""Relay — your Git workflow, on autopilot."""
from __future__ import annotations

import urllib.request

__version__ = "1.0.2"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject HTTP redirects for API calls to prevent credential leakage."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Install safe opener globally so urllib.request.urlopen rejects redirects by default.
urllib.request.install_opener(urllib.request.build_opener(_NoRedirectHandler))

