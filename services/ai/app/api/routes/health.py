from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/ai/health")
async def health():
    return {"status": "ok", "service": "ai"}
