from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/notifications/health")
async def health():
    return {"status": "ok", "service": "notifications"}
