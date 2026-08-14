from fastapi import FastAPI, Depends
from .auth import bootstrap_local_admin
from .database import get_session, get_sessionmaker, init_db
from .routers import auth, documents, qa, search
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

app = FastAPI(title="Document Intelligence Platform - API", version="0.1.0")

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"]) 
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(qa.router, prefix="/api/v1", tags=["qa"])


@app.on_event("startup")
async def on_startup():
    # initialize DB (create tables) in dev/test
    await init_db()
    async with get_sessionmaker()() as session:
        await bootstrap_local_admin(session)


@app.get("/api/v1/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    # check a lightweight DB interaction for readiness
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        logging.exception("Health check DB query failed")
        return {"status": "error"}
