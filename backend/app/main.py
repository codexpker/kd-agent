from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import get_settings

settings = get_settings()
app = FastAPI(
    title="科大 Agent API",
    version="0.2.0-reconstructed",
    description="Evidence-grounded paper reverse engineering API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

