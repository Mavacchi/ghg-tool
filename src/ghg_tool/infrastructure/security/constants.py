"""Shared security constants for token TTLs and related values.

Centralises literal TTL values so that auth.py, totp.py, and jwt.py
all reference one definition.  Import these constants; never hard-code
the numeric literals in individual modules.

R-10: shared TTL constant (review finding R-10).
"""

from __future__ import annotations

# Partial pre-2FA token lifetime (seconds).  Must be short enough to
# limit the replay window while giving users time to enter their OTP.
PARTIAL_TOKEN_TTL_S: int = 300  # 5 minutes

# Full access token lifetime (seconds) -- NFR-05.
ACCESS_TOKEN_TTL_S: int = 3600  # 1 hour

# Refresh token lifetime (seconds) -- NFR-05.
REFRESH_TOKEN_TTL_S: int = 86400  # 24 hours
