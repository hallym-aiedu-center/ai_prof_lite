import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


from core.body_limit import BodyLimitMiddleware
from core.config import positive_int, session_secret
from core.database.migrations import init_database
from core.security_headers import SecurityHeadersMiddleware
from core.version import __version__
from modules.auth.routes import router as auth_router
from modules.auth.session import ActiveSessionMiddleware, AuthenticatedUploadMiddleware
from modules.credentials.routes import router as credentials_router
from modules.dashboard.routes import router as dashboard_router
from modules.instructor.repository import ensure_instructor_schema
from modules.instructor.routes import router as instructor_router
from modules.instructor.scheduler import (
    start_instructor_scheduler,
    stop_instructor_scheduler,
)
from modules.lecture.cleanup import cleanup_all_orphan_runs
from modules.lecture.publish_scheduler import (
    start_publish_scheduler,
    stop_publish_scheduler,
)
from modules.lecture.routes import router as lecture_router
from modules.moodle.courses.routes import (
    api_router as moodle_courses_api_router,
)
from modules.moodle.courses.routes import (
    router as moodle_courses_router,
)
from modules.users.routes import router as users_router
from worker import serve as serve_lecture_worker

logger = logging.getLogger("uvicorn.error")


async def _start_embedded_lecture_worker(app: FastAPI) -> None:
    """Start the GPU lecture supervisor inside the FastAPI process.

    Uvicorn owns OS signals.  The embedded worker receives an asyncio Event
    from the app and is stopped from lifespan shutdown.  Startup waits until
    the worker has acquired its singleton lock and initialized the queue, so a
    broken worker cannot leave the UI accepting jobs that will never run.
    """
    stop = asyncio.Event()
    ready = asyncio.Event()
    task = asyncio.create_task(
        serve_lecture_worker(
            stop,
            install_signal_handlers=False,
            ready=ready,
        ),
        name="embedded-lecture-worker",
    )
    ready_waiter = asyncio.create_task(ready.wait())
    try:
        done, _ = await asyncio.wait(
            {task, ready_waiter},
            timeout=15,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            # Propagate startup/config/lock errors instead of silently serving a
            # web app whose jobs remain forever in "생성 대기".
            await task
            raise RuntimeError("Lecture worker exited during application startup.")
        if ready_waiter not in done:
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise RuntimeError("Lecture worker did not become ready within 15 seconds.")
    finally:
        ready_waiter.cancel()
        await asyncio.gather(ready_waiter, return_exceptions=True)

    app.state.lecture_worker_stop = stop
    app.state.lecture_worker_task = task

    def worker_done(finished: asyncio.Task) -> None:
        if stop.is_set() or finished.cancelled():
            return
        try:
            exc = finished.exception()
        except asyncio.CancelledError:
            return
        logger.critical("Embedded lecture worker exited unexpectedly", exc_info=exc)
        # Do not keep serving a UI that can only accumulate queued jobs.  Uvicorn
        # (and --reload, systemd, Docker, etc.) can restart the app cleanly.
        with suppress(ProcessLookupError):
            os.kill(os.getpid(), signal.SIGTERM)

    task.add_done_callback(worker_done)
    logger.info("Embedded lecture worker is ready")


async def _stop_embedded_lecture_worker(app: FastAPI) -> None:
    stop = getattr(app.state, "lecture_worker_stop", None)
    task = getattr(app.state, "lecture_worker_task", None)
    if stop is None or task is None:
        return

    stop.set()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=20)
    except asyncio.TimeoutError:
        logger.warning("Embedded lecture worker did not stop in time; cancelling")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    except Exception:
        # Shutdown must continue even if the worker had already failed.
        logger.exception("Embedded lecture worker stopped with an error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    await ensure_instructor_schema()
    await cleanup_all_orphan_runs()

    publish_started = False
    instructor_started = False
    try:
        await start_publish_scheduler()
        publish_started = True
        await start_instructor_scheduler()
        instructor_started = True
        await _start_embedded_lecture_worker(app)
        yield
    finally:
        await _stop_embedded_lecture_worker(app)
        if instructor_started:
            await stop_instructor_scheduler()
        if publish_started:
            await stop_publish_scheduler()


app = FastAPI(
    title="AI Professor Lite",
    version=__version__,
    lifespan=lifespan,
)


# Order matters: SessionMiddleware is outermost, then ActiveSessionMiddleware
# invalidates disabled accounts, then AuthenticatedUploadMiddleware can reject
# anonymous uploads before multipart parsing/spooling begins.
app.add_middleware(AuthenticatedUploadMiddleware)
app.add_middleware(ActiveSessionMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="ai_prof_session",
    same_site="lax",
    https_only=(
        os.getenv(
            "APP_ENV",
            "development",
        ).lower()
        == "production"
    ),
    max_age=60 * 60 * 24 * 14,
)


app.add_middleware(SecurityHeadersMiddleware)
trusted_hosts = [
    item.strip() for item in os.getenv("TRUSTED_HOSTS", "").split(",") if item.strip()
]
if trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth_router)
app.add_middleware(
    BodyLimitMiddleware,
    max_bytes=(
        positive_int("MAX_PORTRAIT_BYTES", 10 * 1024 * 1024)
        + positive_int("MAX_REFERENCE_UPLOAD_BYTES", 25 * 1024 * 1024)
        + 512 * 1024
    ),
)
app.include_router(dashboard_router)
app.include_router(users_router)
app.include_router(credentials_router)
app.include_router(lecture_router)
app.include_router(instructor_router)

app.include_router(moodle_courses_router)

app.include_router(moodle_courses_api_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8001")),
        reload=os.getenv("APP_RELOAD", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        proxy_headers=True,
        forwarded_allow_ips=os.getenv(
            "FORWARDED_ALLOW_IPS",
            "127.0.0.1",
        ),
    )
