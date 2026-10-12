from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.meta_service import (
    MetaAPIError,
    meta_service,
)

router = APIRouter(
    prefix="/api/whatsapp",
    tags=["WhatsApp"],
)


class SendMessageRequest(BaseModel):
    phone_number_id: str
    recipient: str
    message: str


@router.post("/send")
async def send_message(
    request: SendMessageRequest,
):

    try:

        result = await meta_service.send_text_message(
            phone_number_id=request.phone_number_id,
            recipient=request.recipient,
            message=request.message,
        )

        return {
            "success": True,
            "meta_response": result,
        }

    except MetaAPIError as exc:

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to send WhatsApp message.",
                "meta_status": exc.status_code,
                "meta_error": exc.detail,
            },
        ) from exc