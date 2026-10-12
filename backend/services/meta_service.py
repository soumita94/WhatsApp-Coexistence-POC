"""
MetaService — all server-side calls to the Meta Graph API.

Rules enforced here:
  - access_token / app_secret never appear in return values.
  - All tokens flow through Authorization: Bearer headers.
  - All errors raise MetaAPIError with status + detail.
"""

from typing import Any

import httpx

from config import settings


class MetaAPIError(Exception):
    """Raised when a Meta Graph API call returns an HTTP error."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Meta API error {status_code}: {detail}")


class MetaService:

    @property
    def base_url(self) -> str:
        # Re-read from settings each time so that hot-reloaded .env
        # changes (during development) are picked up.
        return (
            f"https://graph.facebook.com/"
            f"{settings.meta_graph_version}"
        )

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    async def _get(
        self,
        path: str,
        token: str,
        params: dict | None = None,
    ) -> dict:

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers, params=params)

        data = response.json()

        if response.is_error:
            raise MetaAPIError(response.status_code, data)

        return data

    async def _post(
        self,
        path: str,
        token: str,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict:

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=json,
            )

        data = response.json()

        if response.is_error:
            raise MetaAPIError(response.status_code, data)

        return data

    # ------------------------------------------------------------------
    # Step 1 — Exchange Embedded Signup authorization code
    #
    # Uses the OAuth token endpoint. App Secret is kept server-side
    # and is never returned to the caller.
    # ------------------------------------------------------------------

    async def exchange_signup_code(self, code: str) -> dict:
        """
        Exchanges an Embedded Signup authorization code for an access token.

        The access_token in the response is intentionally NOT returned
        to the frontend. The caller (onboarding route) only returns a
        boolean success indicator.
        """

        params = {
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "code": code,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/oauth/access_token",
                params=params,
            )

        data = response.json()

        if response.is_error:
            raise MetaAPIError(response.status_code, data)

        return data

    # ------------------------------------------------------------------
    # Step 2 — Discover WABAs shared with the AXIOM business account
    # ------------------------------------------------------------------

    async def get_shared_wabas(self) -> dict:
        """
        Fetches WhatsApp Business Accounts that have been shared with
        the AXIOM Meta Business account through Embedded Signup.
        """

        return await self._get(
            f"{settings.meta_business_id}/client_whatsapp_business_accounts",
            token=settings.meta_system_user_access_token,
        )

    # ------------------------------------------------------------------
    # Step 3 — Get phone numbers for a WABA
    # ------------------------------------------------------------------

    async def get_phone_numbers(self, waba_id: str) -> dict:
        """Returns phone numbers registered under the given WABA."""

        return await self._get(
            f"{waba_id}/phone_numbers",
            token=settings.meta_system_user_access_token,
            params={
                "fields": (
                    "id,"
                    "display_phone_number,"
                    "verified_name,"
                    "name_status,"
                    "code_verification_status"
                )
            },
        )

    # ------------------------------------------------------------------
    # Step 4 — Assign AXIOM System User to customer WABA
    #
    # FIX: tasks must be passed as a repeated query parameter, not
    # as the string "['MANAGE','DEVELOP']". The Meta Graph API
    # accepts multi-value params like tasks=MANAGE&tasks=DEVELOP.
    # ------------------------------------------------------------------

    async def assign_system_user(self, waba_id: str) -> dict:
        """
        Assigns the AXIOM System User to the customer's WABA with
        MANAGE and DEVELOP permissions.

        IMPORTANT: Does NOT register or migrate any phone number.
        Coexistence phone numbers remain under the WhatsApp Business App.
        """

        url = f"{self.base_url}/{waba_id}/assigned_users"
        headers = {
            "Authorization": (
                f"Bearer {settings.meta_system_user_access_token}"
            )
        }

        # tasks must be sent as repeated query params.
        # httpx accepts a list of tuples for this.
        params = [
            ("user", settings.meta_system_user_id),
            ("tasks", "MANAGE"),
            ("tasks", "DEVELOP"),
        ]

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
            )

        data = response.json()

        if response.is_error:
            raise MetaAPIError(response.status_code, data)

        return data

    # ------------------------------------------------------------------
    # Step 5 — Subscribe AXIOM app to customer WABA
    # ------------------------------------------------------------------

    async def subscribe_waba(self, waba_id: str) -> dict:
        """
        Subscribes the AXIOM Meta app to the customer's WABA so that
        Meta delivers webhook events to AXIOM's webhook endpoint.
        """

        return await self._post(
            f"{waba_id}/subscribed_apps",
            token=settings.meta_system_user_access_token,
        )

    # ------------------------------------------------------------------
    # Step 6 — Send a text message via Cloud API
    # ------------------------------------------------------------------

    async def send_text_message(
        self,
        phone_number_id: str,
        recipient: str,
        message: str,
    ) -> dict:
        """
        Sends a text message via the WhatsApp Cloud API.

        phone_number_id : the Cloud API phone number resource ID
        recipient       : the customer's phone number (E.164 format)
        message         : plain text body
        """

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message,
            },
        }

        return await self._post(
            f"{phone_number_id}/messages",
            token=settings.meta_system_user_access_token,
            json=payload,
        )


meta_service = MetaService()