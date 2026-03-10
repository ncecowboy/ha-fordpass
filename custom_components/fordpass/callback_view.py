"""HTTP callback view for receiving OAuth tokens from Ford."""
import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.data_entry_flow import UnknownFlow

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
        state = request.query.get("state")  # Contains the config flow ID

        _LOGGER.debug("FordPass OAuth callback received, state=%s, code_present=%s", state, bool(code))

        if not code or not state:
            _LOGGER.warning("FordPass callback missing code or state parameter")
            return web.Response(text=ERROR_HTML, content_type="text/html", status=400)

        try:
            # Advance the config flow with the received code
            await hass.config_entries.flow.async_configure(
                state, user_input={"code": code}
            )
            _LOGGER.debug("Successfully advanced FordPass config flow %s", state)
            return web.Response(text=SUCCESS_HTML, content_type="text/html")
        except UnknownFlow:
            _LOGGER.error("FordPass config flow %s not found; it may have expired", state)
            return web.Response(text=ERROR_HTML, content_type="text/html", status=400)
