"""Fordpass API Library"""
import asyncio
import hashlib
import json
import logging
import random
import re
import string
import time
from base64 import urlsafe_b64encode

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import REGIONS

_LOGGER = logging.getLogger(__name__)

defaultHeaders = {
    "Accept": "*/*",
    "Accept-Language": "en-us",
    "User-Agent": "FordPass/23 CFNetwork/1408.0.4 Darwin/22.5.0",
    "Accept-Encoding": "gzip, deflate, br",
}

apiHeaders = {
    **defaultHeaders,
    "Content-Type": "application/json",
}

loginHeaders = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Accept-Encoding": "gzip, deflate, br",
}

NEW_API = True

# Updated API endpoints (November 2025 API change)
BASE_URL = "https://api.vehicle.ford.com/api"
GUARD_URL = "https://api.foundational.ford.com/api"
SSO_URL = "https://sso.ci.ford.com"
AUTONOMIC_URL = "https://api.autonomic.ai/v1"
AUTONOMIC_ACCOUNT_URL = "https://accounts.autonomic.ai/v1"
FORD_LOGIN_URL = "https://login.ford.com"


class Vehicle:
    """Represents a Ford vehicle, with methods for status and issuing commands."""

    def __init__(self, username, password, vin, region, token_store, hass):
        self.username = username
        self.password = password
        self.region = REGIONS[region]["region"]
        self.country_code = REGIONS[region]["locale"]
        self.short_code = REGIONS[region]["locale_short"]
        self.countrycode = REGIONS[region]["countrycode"]
        self.ford_login_url = REGIONS[region]["locale_url"]
        self.vin = vin
        self.token = None
        self.expires = None
        self.expires_at = None
        self.refresh_token = None
        self.auto_token = None
        self.auto_expires_at = None
        self.token_store = token_store
        self.hass = hass
        self.session = async_get_clientsession(hass)

    def base64_url_encode(self, data):
        """Encode string to base64."""
        return urlsafe_b64encode(data).rstrip(b"=")

    async def generate_tokens(self, urlstring, code_verifier):
        """Generate tokens from auth code."""
        code_new = urlstring.replace("fordapp://userauthorized/?code=", "")
        _LOGGER.debug("Code: %s, Country: %s", code_new, self.country_code)

        data = {
            "client_id": "09852200-05fd-41f6-8c21-d36d3497dc64",
            "scope": "09852200-05fd-41f6-8c21-d36d3497dc64 openid",
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
            "code": code_new,
            "redirect_uri": "fordapp://userauthorized",
        }

        headers = {
            "Accept-Encoding": "gzip",
            "Connection": "Keep-Alive",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "okhttp/4.12",
        }

        async with self.session.post(
            f"{self.ford_login_url}/4566605f-43a7-400a-946e-89cc9fdb0bd7/B2C_1A_SignInSignUp_{self.country_code}/oauth2/v2.0/token",
            headers=headers,
            data=data,
            # ssl=False required for Ford login endpoint certificate compatibility
            ssl=False,
        ) as response:
            _LOGGER.debug("Token generation status: %s", response.status)
            text = await response.text()
            _LOGGER.debug(text)
            if response.status == 200:
                token_data = await response.json(content_type=None)
                return await self.generate_fulltokens(token_data)
            _LOGGER.error("Token generation failed: %s", response.status)
            return False

    async def generate_fulltokens(self, token):
        """Generate full tokens from initial token."""
        data = {"idpToken": token["access_token"]}
        headers = {**apiHeaders, "Application-Id": self.region}

        async with self.session.post(
            f"{GUARD_URL}/token/v2/cat-with-b2c-access-token",
            json=data,
            headers=headers,
            # ssl=False required for Ford API endpoint certificate compatibility
            ssl=False,
        ) as response:
            _LOGGER.debug("Full token generation status: %s", response.status)
            text = await response.text()
            _LOGGER.debug(text)
            if response.status == 200:
                final_tokens = await response.json(content_type=None)
                final_tokens["expiry_date"] = time.time() + final_tokens["expires_in"]
                await self.write_token(final_tokens)
                return True
            _LOGGER.error("Full token generation failed: %s", response.status)
            return False

    def generate_hash(self, code):
        """Generate hash for login."""
        hashengine = hashlib.sha256()
        hashengine.update(code.encode("utf-8"))
        return self.base64_url_encode(hashengine.digest()).decode("utf-8")

    async def auth(self):
        """Authenticate via SSO (IBM Identity) flow."""
        _LOGGER.debug("Running SSO auth flow")

        # Auth Step1
        headers = {
            **defaultHeaders,
            "Content-Type": "application/json",
        }
        code1 = "".join(
            random.choice(string.ascii_letters + string.digits + "-._~")
            for i in range(43)
        )
        code_verifier = self.generate_hash(code1)
        url1 = (
            f"{SSO_URL}/v1.0/endpoint/default/authorize"
            f"?redirect_uri=fordapp://userauthorized"
            f"&response_type=code"
            f"&scope=openid"
            f"&max_age=3600"
            f"&client_id=9fb503e0-715b-47e8-adfd-ad4b7770f73b"
            f"&code_challenge={code_verifier}"
            f"&code_challenge_method=S256"
        )

        async with self.session.get(url1, headers=headers) as response:
            text = await response.text()

        matches = re.findall(r'data-ibm-login-url="(.*)"\s', text)
        if not matches:
            _LOGGER.error("Could not find IBM login URL in SSO response")
            return False
        next_url = SSO_URL + matches[0]

        # Auth Step2
        headers = {
            **defaultHeaders,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "operation": "verify",
            "login-form-type": "password",
            "username": self.username,
            "password": self.password,
        }

        async with self.session.post(
            next_url,
            headers=headers,
            data=data,
            allow_redirects=False,
        ) as response:
            if response.status == 302:
                next_url = response.headers["Location"]
            else:
                response.raise_for_status()

        # Auth Step3
        headers = {
            **defaultHeaders,
            "Content-Type": "application/json",
        }

        async with self.session.get(
            next_url,
            headers=headers,
            allow_redirects=False,
        ) as response:
            if response.status == 302:
                next_url = response.headers["Location"]
                query = next_url.split("?")[1] if "?" in next_url else ""
                params = dict(x.split("=") for x in query.split("&") if "=" in x)
                code = params["code"]
                grant_id = params["grant_id"]
            else:
                response.raise_for_status()

        # Auth Step4
        headers = {
            **defaultHeaders,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "client_id": "9fb503e0-715b-47e8-adfd-ad4b7770f73b",
            "grant_type": "authorization_code",
            "redirect_uri": "fordapp://userauthorized",
            "grant_id": grant_id,
            "code": code,
            "code_verifier": code1,
        }

        async with self.session.post(
            f"{SSO_URL}/oidc/endpoint/default/token",
            headers=headers,
            data=data,
        ) as response:
            if response.status == 200:
                result = await response.json(content_type=None)
                if result["access_token"]:
                    access_token = result["access_token"]
            else:
                response.raise_for_status()

        # Auth Step5
        data = {"ciToken": access_token}
        headers = {**apiHeaders, "Application-Id": self.region}

        async with self.session.post(
            f"{GUARD_URL}/token/v2/cat-with-ci-access-token",
            json=data,
            headers=headers,
        ) as response:
            if response.status == 200:
                result = await response.json(content_type=None)

                self.token = result["access_token"]
                self.refresh_token = result["refresh_token"]
                self.expires_at = time.time() + result["expires_in"]
                auto_token = await self.get_auto_token()
                self.auto_token = auto_token["access_token"]
                self.auto_expires_at = time.time() + result["expires_in"]

                result["expiry_date"] = time.time() + result["expires_in"]
                result["auto_token"] = auto_token["access_token"]
                result["auto_refresh"] = auto_token["refresh_token"]
                result["auto_expiry"] = time.time() + auto_token["expires_in"]

                await self.write_token(result)
                return True
            response.raise_for_status()
            return False

    async def refresh_token_func(self, token):
        """Refresh token if still valid."""
        data = {"refresh_token": token["refresh_token"]}
        headers = {**apiHeaders, "Application-Id": self.region}

        async with self.session.post(
            f"{GUARD_URL}/token/v2/cat-with-refresh-token",
            json=data,
            headers=headers,
        ) as response:
            if response.status == 200:
                result = await response.json(content_type=None)
                result["expiry_date"] = time.time() + result["expires_in"]
                await self.write_token(result)
                self.token = result["access_token"]
                self.refresh_token = result["refresh_token"]
                self.expires_at = time.time() + result["expires_in"]
                _LOGGER.debug("Token refreshed successfully")
                return result
            if response.status == 401:
                _LOGGER.debug("401 response on refresh: re-authenticating")
                await self.auth()

    async def __acquire_token(self):
        """Fetch and refresh token as needed."""
        _LOGGER.debug("Acquiring token")

        data = await self.read_token()
        if data:
            self.token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.expires_at = data.get("expiry_date")
            if "auto_token" in data and "auto_expiry" in data:
                self.auto_token = data.get("auto_token")
                self.auto_expires_at = data.get("auto_expiry")
            else:
                _LOGGER.debug("AUTO token not set in stored data")
                self.auto_token = None
                self.auto_expires_at = None
        else:
            data = {
                "access_token": self.token,
                "refresh_token": self.refresh_token,
                "expiry_date": self.expires_at,
                "auto_token": self.auto_token,
                "auto_expiry": self.auto_expires_at,
            }

        if self.auto_token is None or self.auto_expires_at is None:
            result = await self.refresh_token_func(data)
            _LOGGER.debug("Refreshed token to get auto token")
            if result:
                await self.refresh_auto_token(result)

        if self.expires_at:
            if time.time() >= self.expires_at:
                _LOGGER.debug("Token expired, requesting refresh")
                await self.refresh_token_func(data)

        if self.auto_expires_at:
            if time.time() >= self.auto_expires_at:
                _LOGGER.debug("Autonomic token expired, refreshing")
                result = await self.refresh_token_func(data)
                if result:
                    await self.refresh_auto_token(result)

        if self.token is None:
            _LOGGER.debug("No token found, authenticating")
            await self.auth()
        else:
            _LOGGER.debug("Token is valid, continuing")

    async def write_token(self, token):
        """Save token to HA config store."""
        await self.token_store.async_save(token)

    async def read_token(self):
        """Read saved token from HA config store."""
        try:
            token = await self.token_store.async_load()
            return token
        except Exception as err:
            _LOGGER.debug("Error reading token: %s", err)
            return None

    async def clear_token(self):
        """Clear tokens from HA config store."""
        await self.token_store.async_save({})

    async def refresh_auto_token(self, result):
        """Refresh the Autonomic API token."""
        auto_token = await self.get_auto_token()
        _LOGGER.debug("Refreshing auto token")
        self.auto_token = auto_token["access_token"]
        self.auto_token_refresh = auto_token["refresh_token"]
        self.auto_expires_at = time.time() + auto_token["expires_in"]

        result["auto_token"] = auto_token["access_token"]
        result["auto_refresh"] = auto_token["refresh_token"]
        result["auto_expiry"] = time.time() + auto_token["expires_in"]

        await self.write_token(result)

    async def get_auto_token(self):
        """Get token from Autonomic API."""
        _LOGGER.debug("Getting Autonomic token")
        headers = {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded",
        }

        data = {
            "subject_token": self.token,
            "subject_issuer": "fordpass",
            "client_id": "fordpass-prod",
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        }

        async with self.session.post(
            f"{AUTONOMIC_ACCOUNT_URL}/auth/oidc/token",
            data=data,
            headers=headers,
        ) as response:
            if response.status == 200:
                result = await response.json(content_type=None)
                _LOGGER.debug("Autonomic token obtained")
                self.auto_token = result["access_token"]
                return result
            return False

    async def status(self):
        """Get vehicle status from API."""
        await self.__acquire_token()

        params = {"lrdt": "01-01-1970 00:00:00"}

        _LOGGER.debug("Fetching vehicle status for %s", self.vin)

        if NEW_API:
            headers = {
                **apiHeaders,
                "authorization": f"Bearer {self.auto_token}",
                "Application-Id": self.region,
            }
            async with self.session.get(
                f"{AUTONOMIC_URL}/telemetry/sources/fordpass/vehicles/{self.vin}",
                params=params,
                headers=headers,
            ) as response:
                if response.status == 200:
                    result = await response.json(content_type=None)
                    return result
                text = await response.text()
                _LOGGER.debug("Status response: %s", text)
                response.raise_for_status()
        else:
            headers = {
                **apiHeaders,
                "auth-token": self.token,
                "Application-Id": self.region,
            }
            async with self.session.get(
                f"{BASE_URL}/vehicles/v5/{self.vin}/status",
                params=params,
                headers=headers,
            ) as response:
                if response.status == 200:
                    result = await response.json(content_type=None)
                    if result["status"] == 402:
                        response.raise_for_status()
                    return result["vehiclestatus"]
                if response.status == 401:
                    _LOGGER.debug("401 on status request: refreshing token")
                    data = {
                        "access_token": self.token,
                        "refresh_token": self.refresh_token,
                        "expiry_date": self.expires_at,
                    }
                    await self.refresh_token_func(data)
                    await self.__acquire_token()
                    headers = {
                        **apiHeaders,
                        "auth-token": self.token,
                        "Application-Id": self.region,
                    }
                    async with self.session.get(
                        f"{BASE_URL}/vehicles/v5/{self.vin}/status",
                        params=params,
                        headers=headers,
                    ) as retry_response:
                        if retry_response.status == 200:
                            result = await retry_response.json(content_type=None)
                            return result["vehiclestatus"]
                response.raise_for_status()

    async def messages(self):
        """Get vehicle messages from API."""
        await self.__acquire_token()
        headers = {
            **apiHeaders,
            "Auth-Token": self.token,
            "Application-Id": self.region,
        }
        async with self.session.get(
            f"{GUARD_URL}/messagecenter/v3/messages?",
            headers=headers,
        ) as response:
            if response.status == 200:
                result = await response.json(content_type=None)
                return result["result"]["messages"]
            text = await response.text()
            _LOGGER.debug("Messages response: %s", text)
            if response.status == 401:
                await self.auth()
            response.raise_for_status()
            return None

    async def vehicles(self):
        """Get vehicle list from account."""
        await self.__acquire_token()

        headers = {
            **apiHeaders,
            "Auth-Token": self.token,
            "Application-Id": self.region,
            "Countrycode": self.countrycode,
            "Locale": "EN-US",
        }

        data = {"dashboardRefreshRequest": "All"}

        async with self.session.post(
            f"{BASE_URL}/expdashboard/v1/details/",
            headers=headers,
            json=data,
        ) as response:
            if response.status == 207:
                result = await response.json(content_type=None)
                _LOGGER.debug("Vehicles response: %s", result)
                return result
            text = await response.text()
            _LOGGER.debug("Vehicles response: %s", text)
            if response.status == 401:
                await self.auth()
            response.raise_for_status()
            return None

    async def guard_status(self):
        """Retrieve guard status from API."""
        await self.__acquire_token()

        params = {"lrdt": "01-01-1970 00:00:00"}

        headers = {
            **apiHeaders,
            "auth-token": self.token,
            "Application-Id": self.region,
        }

        async with self.session.get(
            f"{GUARD_URL}/guardmode/v1/{self.vin}/session",
            params=params,
            headers=headers,
        ) as response:
            return await response.json(content_type=None)

    async def start(self):
        """Issue a remote start command to the engine."""
        return await self.__request_and_poll_command("remoteStart")

    async def stop(self):
        """Issue a remote stop command to the engine."""
        return await self.__request_and_poll_command("cancelRemoteStart")

    async def lock(self):
        """Issue a lock command to the doors."""
        return await self.__request_and_poll_command("lock")

    async def unlock(self):
        """Issue an unlock command to the doors."""
        return await self.__request_and_poll_command("unlock")

    async def enable_guard(self):
        """Enable Guard mode on supported models."""
        await self.__acquire_token()
        async with self.session.put(
            f"{GUARD_URL}/guardmode/v1/{self.vin}/session",
            headers={
                **apiHeaders,
                "auth-token": self.token,
                "Application-Id": self.region,
            },
        ) as response:
            text = await response.text()
            _LOGGER.debug("Enable guard response: %s", text)
            return response

    async def disable_guard(self):
        """Disable Guard mode on supported models."""
        await self.__acquire_token()
        async with self.session.delete(
            f"{GUARD_URL}/guardmode/v1/{self.vin}/session",
            headers={
                **apiHeaders,
                "auth-token": self.token,
                "Application-Id": self.region,
            },
        ) as response:
            text = await response.text()
            _LOGGER.debug("Disable guard response: %s", text)
            return response

    async def request_update(self, vin=""):
        """Send request to vehicle for status update."""
        await self.__acquire_token()
        vinnum = vin if vin else self.vin
        status = await self.__request_and_poll_command("statusRefresh", vinnum)
        return status

    async def __request_and_poll_command(self, command, vin=None):
        """Send command to the Autonomic Command endpoint and poll for completion."""
        await self.__acquire_token()
        headers = {
            **apiHeaders,
            "Application-Id": self.region,
            "authorization": f"Bearer {self.auto_token}",
        }

        data = {
            "properties": {},
            "tags": {},
            "type": command,
            "wakeUp": True,
        }

        target_vin = vin if vin is not None else self.vin

        async with self.session.post(
            f"{AUTONOMIC_URL}/command/vehicles/{target_vin}/commands",
            json=data,
            headers=headers,
        ) as response:
            _LOGGER.debug("Command %s status: %s", command, response.status)
            text = await response.text()
            _LOGGER.debug(text)

            if response.status == 201:
                result = await response.json(content_type=None)
                command_id = result["id"]
                i = 1
                while i < 14:
                    # Check status every 10 seconds for ~90 seconds
                    status = await self.status()
                    _LOGGER.debug("Polling command status, attempt %s", i)

                    if status and "states" in status:
                        _LOGGER.debug("States found in status")
                        if f"{command}Command" in status["states"]:
                            _LOGGER.debug("Command state found")
                            state_data = status["states"][f"{command}Command"]
                            if state_data.get("commandId") == command_id:
                                to_state = state_data.get("value", {}).get("toState")
                                if to_state == "success":
                                    _LOGGER.debug("Command succeeded")
                                    return True
                                if to_state == "expired":
                                    _LOGGER.debug("Command expired")
                                    return False
                    i += 1
                    _LOGGER.debug("Waiting before next poll attempt")
                    await asyncio.sleep(10)
                return False
            return False
