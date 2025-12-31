"""
Rate limiter configuration.
Uses slowapi for IP-based rate limiting.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter (uses client IP)
limiter = Limiter(key_func=get_remote_address)
