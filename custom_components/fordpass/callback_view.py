"""HTTP callback view for receiving OAuth tokens from Ford."""
import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.data_entry_flow import UnknownFlow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FordPass Authentication</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; margin: 0; background: #f5f5f5;
        }
        .card {
            background: white; border-radius: 12px; padding: 40px;
            text-align: center; max-width: 400px; box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        .icon { font-size: 64px; margin-bottom: 16px; }
        h1 { color: #1a73e8; margin: 0 0 12px; font-size: 24px; }
        p { color: #555; margin: 0; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✅</div>
        <h1>Authentication Successful</h1>
        <p>Your Ford account has been linked to Home Assistant.<br>
        You can close this window and return to Home Assistant to complete setup.</p>
    </div>
</body>
</html>
"""

ERROR_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FordPass Authentication</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; margin: 0; background: #f5f5f5;
        }
        .card {
            background: white; border-radius: 12px; padding: 40px;
            text-align: center; max-width: 400px; box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        .icon { font-size: 64px; margin-bottom: 16px; }
        h1 { color: #d32f2f; margin: 0 0 12px; font-size: 24px; }
        p { color: #555; margin: 0; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">❌</div>
        <h1>Authentication Failed</h1>
        <p>Could not process the authentication response. Please return to Home Assistant
        and try again, or use the manual URL entry option.</p>
    </div>
</body>
</html>
"""


class FordPassCallbackView(HomeAssistantView):
    """Handle OAuth callback from Ford's login redirect."""

    url = "/api/fordpass/callback"
    name = "api:fordpass:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request with OAuth authorization code."""
        hass = request.app["hass"]

        code = request.query.get("code")
        nonce = request.query.get("state")  # Random nonce; maps to the flow ID server-side

        _LOGGER.debug("FordPass OAuth callback received, nonce_present=%s, code_present=%s", bool(nonce), bool(code))

        if not code or not nonce:
            _LOGGER.warning("FordPass callback missing code or state parameter")
            return web.Response(text=ERROR_HTML, content_type="text/html", status=400)

        # Resolve the nonce to the actual config flow ID and consume it (one-time use).
        nonce_map = hass.data.get(DOMAIN, {}).get("oauth_nonces", {})
        flow_id = nonce_map.pop(nonce, None)

        if flow_id is None:
            _LOGGER.warning("FordPass callback received unknown or already-used nonce")
            return web.Response(text=ERROR_HTML, content_type="text/html", status=400)

        try:
            # Verify the flow exists and belongs to the FordPass integration
            # before advancing it with the received code.
            # async_get() raises UnknownFlow when the flow doesn't exist.
            flow = hass.config_entries.flow.async_get(flow_id)
            if not flow or flow.get("handler") != DOMAIN:
                _LOGGER.warning(
                    "FordPass callback: flow %s does not belong to %s", flow_id, DOMAIN
                )
                return web.Response(text=ERROR_HTML, content_type="text/html", status=400)

            await hass.config_entries.flow.async_configure(
                flow_id, user_input={"code": code}
            )
            _LOGGER.debug("Successfully advanced FordPass config flow %s", flow_id)
            return web.Response(text=SUCCESS_HTML, content_type="text/html")
        except UnknownFlow:
            _LOGGER.error("FordPass config flow %s not found; it may have expired", flow_id)
            return web.Response(text=ERROR_HTML, content_type="text/html", status=400)
