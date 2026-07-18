"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.exceptions import register_exception_handlers
from app.core.envelope import ok
from app.api.routers import auth, listings, applications, profiles, notifications, audit
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.audit import AuditMiddleware

app = FastAPI(title="InternLoom Talent Matching API", version="1.0.0")

# Global error handling — guarantees no endpoint crashes with a raw 500.
register_exception_handlers(app)

# Middleware (LIFO: rate limit added last => runs first, before any real work).
app.add_middleware(AuditMiddleware)        # Bonus C — logs successful mutations
app.add_middleware(RateLimitMiddleware)    # Bonus A — 100 req / 15 min / IP
app.add_middleware(                        # Bonus D dashboard runs on another origin
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(applications.router)
app.include_router(profiles.router)
app.include_router(notifications.router)
app.include_router(audit.router)


@app.get("/health")
def health():
    return ok({"status": "ok"})
