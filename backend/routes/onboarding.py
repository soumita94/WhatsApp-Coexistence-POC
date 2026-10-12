"""
Onboarding route — handles the Embedded Signup authorization code
exchange and post-signup WABA setup steps.

URL prefix: /api/onboarding
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.meta_service import (
    MetaAPIError,
    meta_service,
)

router = APIRouter(
    prefix="/api/onboarding",
    tags=["WhatsApp Onboarding"],
)


# ---------------------------------------------------------------
# Request model
# ---------------------------------------------------------------

class OnboardingCompleteRequest(BaseModel):
    # Authorization code from Embedded Signup — exchanged server-side.
    code: str

    # Optional metadata from WA_EMBEDDED_SIGNUP postMessage event.
    # These are non-secret and help us identify the WABA without an
    # extra API call (if Meta provides them in the event payload).
    waba_id: str | None = None
    phone_number_id: str | None = None
    signup_event: str | None = None


# ---------------------------------------------------------------
# POST /api/onboarding/complete
# ---------------------------------------------------------------

@router.post("/complete")
async def complete_onboarding(
    request: OnboardingCompleteRequest,
):
    """
    Receives the Embedded Signup authorization code from the frontend.

    Steps:
      1. Exchange the code server-side (App ID + App Secret — never
         returned to the frontend).
      2. Discover WABAs shared with AXIOM.
      3. Fetch phone numbers for the WABA.
      4. Assign the AXIOM System User to the WABA.
      5. Subscribe the AXIOM app to the WABA.
      6. Return safe, non-secret connection result.
    """

    # ------------------------------------------------------------------
    # 1. Exchange Embedded Signup authorization code
    # ------------------------------------------------------------------

    try:
        token_response = await meta_service.exchange_signup_code(
            request.code
        )
    except MetaAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Authorization code exchange with Meta failed. "
                    "The code may have expired or been used already."
                ),
                "meta_status": exc.status_code,
                "meta_error": exc.detail,
            },
        ) from exc

    # The token is intentionally NOT returned to the frontend.
    # We record whether exchange succeeded for the response payload.
    exchange_succeeded = bool(token_response.get("access_token"))

    # ------------------------------------------------------------------
    # 2. Discover WABA(s) shared with AXIOM
    #
    # If the Embedded Signup postMessage event provided a waba_id we
    # use it directly (saves an API round-trip). Otherwise we fetch
    # the shared WABAs from Meta.
    # ------------------------------------------------------------------

    waba_id = request.waba_id

    try:
        if waba_id:
            # waba_id was provided by the postMessage event — trust it
            # but still validate it exists on our business account.
            shared_wabas = await meta_service.get_shared_wabas()
            waba_list = shared_wabas.get("data", [])

            # Verify the event-provided ID is in the list.
            known_ids = {w.get("id") for w in waba_list}
            if waba_id not in known_ids:
                # Accept it anyway (coexistence flow may behave differently)
                # but log a warning so it's visible in server output.
                print(
                    f"[AXIOM WARNING] Signup event WABA ID {waba_id!r} "
                    f"not found in get_shared_wabas response. "
                    f"Known IDs: {known_ids}. "
                    f"Proceeding anyway — this is expected for coexistence flow."
                )
        else:
            # No waba_id from event — fetch from Meta.
            shared_wabas = await meta_service.get_shared_wabas()
            waba_list = shared_wabas.get("data", [])

            if not waba_list:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Signup completed, but no shared WABA was found "
                        "for the AXIOM business account. "
                        "Ensure the customer completed the signup flow and "
                        "that the AXIOM app has been granted access."
                    ),
                )

            # Use the first WABA for this POC.
            # Production AXIOM will match by tenant context.
            waba = waba_list[0]
            waba_id = waba.get("id")

            if not waba_id:
                raise HTTPException(
                    status_code=500,
                    detail="Meta returned a WABA record without an ID.",
                )

    except MetaAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed to retrieve shared WABAs from Meta.",
                "meta_status": exc.status_code,
                "meta_error": exc.detail,
            },
        ) from exc

    # ------------------------------------------------------------------
    # 3. Fetch phone numbers for the WABA
    # ------------------------------------------------------------------

    phone_numbers: list[Any] = []

    try:
        phone_result = await meta_service.get_phone_numbers(waba_id)
        phone_numbers = phone_result.get("data", [])
    except MetaAPIError as exc:
        # Non-fatal for the POC — log and continue.
        print(
            f"[AXIOM WARNING] Could not fetch phone numbers for WABA "
            f"{waba_id}: {exc}"
        )

    # ------------------------------------------------------------------
    # 4. Assign AXIOM System User to the WABA
    #
    # IMPORTANT: We do NOT call /register on any phone number.
    # The coexistence flow does not require manual phone registration
    # and doing so would convert the number to API-only.
    # ------------------------------------------------------------------

    system_user_result: dict = {}

    try:
        system_user_result = await meta_service.assign_system_user(waba_id)
    except MetaAPIError as exc:
        # Non-fatal — log and continue.
        print(
            f"[AXIOM WARNING] System user assignment failed for WABA "
            f"{waba_id}: {exc}"
        )
        system_user_result = {
            "warning": "System user assignment failed.",
            "meta_status": exc.status_code,
        }

    # ------------------------------------------------------------------
    # 5. Subscribe AXIOM app to the WABA
    # ------------------------------------------------------------------

    subscription_result: dict = {}

    try:
        subscription_result = await meta_service.subscribe_waba(waba_id)
    except MetaAPIError as exc:
        print(
            f"[AXIOM WARNING] WABA subscription failed for WABA "
            f"{waba_id}: {exc}"
        )
        subscription_result = {
            "warning": "WABA subscription failed.",
            "meta_status": exc.status_code,
        }

    # ------------------------------------------------------------------
    # Return safe, non-secret result
    # ------------------------------------------------------------------

    return {
        "success": True,
        "message": "WhatsApp coexistence onboarding completed.",
        "waba": {
            "id": waba_id,
        },
        "phone_numbers": [
            {
                "id": p.get("id"),
                "display_phone_number": p.get("display_phone_number"),
                "verified_name": p.get("verified_name"),
                "name_status": p.get("name_status"),
            }
            for p in phone_numbers
        ],
        "system_user_assignment": system_user_result,
        "webhook_subscription": subscription_result,
        "token_exchange_success": exchange_succeeded,
        # Reflect back the non-secret event data the frontend sent.
        "signup_event": request.signup_event,
    }