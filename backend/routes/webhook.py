"""
Webhook route — handles Meta webhook verification and event delivery.

URL prefix: /webhook

Meta requires:
  GET  /webhook  — verification challenge
  POST /webhook  — event delivery (must return 200 quickly)

Coexistence-specific fields parsed:
  messages             — incoming customer messages
  statuses             — message delivery status
  smb_message_echoes   — messages sent by human via WhatsApp Business App
  smb_app_state_sync   — state sync between Business App and Cloud API
  history              — message history events
"""

import json

from fastapi import APIRouter, HTTPException, Query, Request, Response

from config import settings

router = APIRouter(
    prefix="/webhook",
    tags=["Webhook"],
)


# ---------------------------------------------------------------
# GET /webhook — Meta webhook verification
# ---------------------------------------------------------------

@router.get("")
async def verify_webhook(
    hub_mode: str | None = Query(
        default=None,
        alias="hub.mode",
    ),
    hub_verify_token: str | None = Query(
        default=None,
        alias="hub.verify_token",
    ),
    hub_challenge: str | None = Query(
        default=None,
        alias="hub.challenge",
    ),
):
    """
    Meta calls this endpoint to verify the webhook URL.
    Must return hub.challenge as plain text with status 200.
    """

    if hub_mode != "subscribe":
        raise HTTPException(
            status_code=400,
            detail="Invalid hub.mode — expected 'subscribe'.",
        )

    if not hub_verify_token or hub_verify_token != settings.meta_webhook_verify_token:
        raise HTTPException(
            status_code=403,
            detail="Invalid verification token.",
        )

    if not hub_challenge:
        raise HTTPException(
            status_code=400,
            detail="Missing hub.challenge.",
        )

    # IMPORTANT: Meta expects the challenge returned as plain text,
    # not as a JSON integer. Use Response() explicitly.
    return Response(
        content=hub_challenge,
        media_type="text/plain",
        status_code=200,
    )


# ---------------------------------------------------------------
# POST /webhook — Meta webhook event delivery
# ---------------------------------------------------------------

@router.post("")
async def receive_webhook(request: Request):
    """
    Receives all WhatsApp webhook events from Meta.

    Must return HTTP 200 quickly. Do not perform long-running
    operations synchronously inside this handler.

    Coexistence-specific events handled:
      - smb_message_echoes : human salesperson message (Business App)
      - smb_app_state_sync : coexistence state synchronization
      - history            : message history for context
    """

    try:
        payload = await request.json()
    except Exception:
        # Meta sends JSON — if parsing fails, log and return 200
        # (do not let Meta retry indefinitely on a bad payload).
        print("[AXIOM WEBHOOK] Could not parse webhook payload as JSON.")
        return {"status": "ok"}

    _process_webhook(payload)

    # Return 200 immediately — never hold this response.
    return {"status": "ok"}


# ---------------------------------------------------------------
# Webhook payload processing
# ---------------------------------------------------------------

def _process_webhook(payload: dict) -> None:
    """
    Parses and logs a Meta webhook payload.

    Structure:
      {
        "object": "whatsapp_business_account",
        "entry": [
          {
            "id": "<WABA_ID>",
            "changes": [
              {
                "field": "messages" | "smb_message_echoes" | ...,
                "value": { ... }
              }
            ]
          }
        ]
      }
    """

    object_type = payload.get("object", "unknown")

    print("\n" + "=" * 70)
    print(f"AXIOM WEBHOOK — object: {object_type}")
    print("=" * 70)

    if object_type != "whatsapp_business_account":
        print(f"  [INFO] Unexpected object type: {object_type}")
        print("=" * 70 + "\n")
        return

    for entry in payload.get("entry", []):
        waba_id = entry.get("id", "unknown")
        print(f"  WABA ID: {waba_id}")

        for change in entry.get("changes", []):
            field = change.get("field", "unknown")
            value = change.get("value", {})

            print(f"\n  field: {field}")
            _dispatch_field(field, value, waba_id)

    print("=" * 70 + "\n")


def _dispatch_field(field: str, value: dict, waba_id: str) -> None:
    """Routes a webhook change to the appropriate handler."""

    if field == "messages":
        _handle_messages(value, waba_id)

    elif field == "smb_message_echoes":
        _handle_smb_message_echoes(value, waba_id)

    elif field == "smb_app_state_sync":
        _handle_smb_app_state_sync(value, waba_id)

    elif field == "history":
        _handle_history(value, waba_id)

    elif field == "message_template_status_update":
        _handle_template_status(value, waba_id)

    else:
        # Unknown field — log for future implementation.
        print(f"  [UNHANDLED field={field!r}]")
        # Avoid logging large payloads verbatim.
        # Summarize the top-level keys only.
        print(f"  value keys: {list(value.keys())}")


# ---------------------------------------------------------------
# Handler: messages (incoming customer messages)
# ---------------------------------------------------------------

def _handle_messages(value: dict, waba_id: str) -> None:
    """Handles incoming messages sent by customers."""

    metadata = value.get("metadata", {})
    phone_number_id = metadata.get("phone_number_id", "unknown")
    display_phone = metadata.get("display_phone_number", "unknown")

    messages = value.get("messages", [])
    contacts = value.get("contacts", [])
    statuses = value.get("statuses", [])

    contact_map = {
        c.get("wa_id"): c.get("profile", {}).get("name", "Unknown")
        for c in contacts
    }

    for msg in messages:
        sender = msg.get("from", "unknown")
        sender_name = contact_map.get(sender, sender)
        msg_type = msg.get("type", "unknown")
        msg_id = msg.get("id", "unknown")
        timestamp = msg.get("timestamp", "unknown")

        body = ""
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "")

        print(
            f"  [INCOMING MESSAGE]\n"
            f"    from       : {sender} ({sender_name})\n"
            f"    type       : {msg_type}\n"
            f"    body       : {body!r}\n"
            f"    message_id : {msg_id}\n"
            f"    timestamp  : {timestamp}\n"
            f"    phone_id   : {phone_number_id} ({display_phone})"
        )

    for status in statuses:
        print(
            f"  [STATUS] id={status.get('id')} "
            f"status={status.get('status')} "
            f"recipient={status.get('recipient_id')}"
        )


# ---------------------------------------------------------------
# Handler: smb_message_echoes (human salesperson messages)
#
# COEXISTENCE — CRITICAL:
#   When the human salesperson sends a message from the
#   WhatsApp Business App, Meta echoes it here.
#   AXIOM must record this as "human activity" so automated
#   responses are suppressed for that conversation.
# ---------------------------------------------------------------

def _handle_smb_message_echoes(value: dict, waba_id: str) -> None:
    """
    Handles messages sent by the human salesperson via the
    WhatsApp Business App (coexistence echo).

    These represent human activity. The AXIOM conversation engine
    must treat these as "human took over" signals and suppress
    automated responses for the affected conversation.
    """

    metadata = value.get("metadata", {})
    phone_number_id = metadata.get("phone_number_id", "unknown")

    messages = value.get("messages", [])

    for msg in messages:
        recipient = msg.get("to", "unknown")
        msg_type = msg.get("type", "unknown")
        msg_id = msg.get("id", "unknown")
        timestamp = msg.get("timestamp", "unknown")

        body = ""
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "")

        print(
            f"  [SMB_MESSAGE_ECHO — HUMAN SALESPERSON SENT]\n"
            f"    to          : {recipient}\n"
            f"    type        : {msg_type}\n"
            f"    body        : {body!r}\n"
            f"    message_id  : {msg_id}\n"
            f"    timestamp   : {timestamp}\n"
            f"    phone_id    : {phone_number_id}\n"
            f"    AXIOM_ACTION: Record human activity → suppress automation"
        )

        # TODO (production): write a "human_activity" event to the
        # conversation store so the AXIOM engine knows a salesperson
        # is actively handling this contact and should not auto-reply.
        #
        # Normalized event shape (future DB/store insert):
        # {
        #   "type": "human_message_echo",
        #   "waba_id": waba_id,
        #   "phone_number_id": phone_number_id,
        #   "recipient": recipient,
        #   "message_id": msg_id,
        #   "message_type": msg_type,
        #   "body": body,
        #   "timestamp": timestamp,
        #   "action": "suppress_automation",
        # }


# ---------------------------------------------------------------
# Handler: smb_app_state_sync (coexistence state events)
# ---------------------------------------------------------------

def _handle_smb_app_state_sync(value: dict, waba_id: str) -> None:
    """
    Handles coexistence state synchronization events between the
    WhatsApp Business App and the Cloud API.

    These events signal connection/disconnection of the Business App
    from the coexistence setup.
    """

    print(
        f"  [SMB_APP_STATE_SYNC — COEXISTENCE STATE CHANGE]\n"
        f"    waba_id : {waba_id}\n"
        f"    payload keys: {list(value.keys())}"
    )

    # Log the full state payload (non-sensitive).
    for k, v in value.items():
        if k not in ("access_token", "token"):
            print(f"    {k}: {v}")


# ---------------------------------------------------------------
# Handler: history (message history for context)
# ---------------------------------------------------------------

def _handle_history(value: dict, waba_id: str) -> None:
    """
    Handles message history events.
    These provide historical conversation context when a number
    is first connected via coexistence.
    """

    print(
        f"  [HISTORY — CONVERSATION HISTORY EVENT]\n"
        f"    waba_id     : {waba_id}\n"
        f"    payload keys: {list(value.keys())}"
    )


# ---------------------------------------------------------------
# Handler: template status update
# ---------------------------------------------------------------

def _handle_template_status(value: dict, waba_id: str) -> None:
    """Handles message template approval/rejection status updates."""

    print(
        f"  [TEMPLATE STATUS UPDATE]\n"
        f"    event     : {value.get('event')}\n"
        f"    template  : {value.get('message_template_name')}\n"
        f"    status    : {value.get('reason')}"
    )