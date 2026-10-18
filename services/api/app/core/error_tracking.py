"""Sentry error tracking — backend only, fails open.

init_error_tracking() is a no-op with SENTRY_DSN unset, mirroring
core/tracing.py's fails-open shape for Langfuse: the existing test
suite (which sets no Sentry env vars) must stay crash-free and
no-op, not error. Checked explicitly rather than trusting
sentry_sdk's own falsy-dsn handling, for the same reason
.env.example warns about langfuse-python treating a blank key as
configured — don't depend on a third-party SDK's own definition of
"unset" matching ours.

Errors only: traces_sample_rate=0. Langfuse (core/tracing.py) is
already the source of truth for pipeline-span timing; enabling
Sentry's own performance tracing on top would duplicate that
instrumentation for no added visibility, plus cost/overhead on the
512MB Render instance.

No FastAPI/Starlette integration import needed — sentry_sdk auto-
enables it once `fastapi` is an installed dependency, confirmed
against Sentry's current docs before writing this.
"""
import os

import sentry_sdk


def init_error_tracking() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("BUILD_SHA", "dev"),
        traces_sample_rate=0,
    )
