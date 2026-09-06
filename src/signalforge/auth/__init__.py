"""Local single-user authentication (ARCHITECTURE.md §12).

Argon2id password hashing, a signed session cookie (via Starlette
``SessionMiddleware``), a synchroniser CSRF token on state-changing forms, and a
failed-login backoff delay. The app binds to loopback by default.
"""

from __future__ import annotations
