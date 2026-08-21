from slowapi import Limiter
from slowapi.util import get_remote_address

# One shared instance. SlowAPI resolves a route's limits through
# app.state.limiter, so a Limiter constructed separately inside a router is
# never consulted and its @limit decorators silently do nothing.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
