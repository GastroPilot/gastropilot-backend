from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/orders/health")
async def health():
    return {"status": "ok", "service": "orders"}
