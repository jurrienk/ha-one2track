"""One2Track API client.

Communicates with www.one2trackgps.com via session-based authentication,
HTML scraping for device state, and form PATCHes for commands.

Command format (reverse engineered from the Rails portal):
  POST /devices/{uuid}/functions
  Body: _method=patch, authenticity_token, function[cmd_code], function[cmd_value][]
"""

from __future__ import annotations

import json
import re
import socket
from html import unescape
from typing import Any
from urllib.parse import urlparse

import aiohttp
import async_timeout

from .const import BASE_URL, LOGIN_URL, LOGGER, SESSION_COOKIE, SESSION_COOKIE_ALT


class One2TrackApiClientError(Exception):
    """Base exception for One2Track API errors."""


class One2TrackApiClientCommunicationError(One2TrackApiClientError):
    """Exception for network/communication errors."""


class One2TrackApiClientAuthenticationError(One2TrackApiClientError):
    """Exception for authentication failures."""


class One2TrackApiClient:
    """Client for the One2Track web application."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._cookie: str = ""
        self._cookie_name: str = SESSION_COOKIE  # determined at login
        self._csrf: str = ""
        self._account_id: str = ""
        self._device_uuids: list[str] = []

    @property
    def account_id(self) -> str:
        """Return the discovered account ID."""
        return self._account_id

    # ── Authentication ──────────────────────────────────────────────

    async def async_authenticate(self) -> str:
        """Full login flow. Returns account_id."""
        await self._async_fetch_csrf()
        await self._async_login()
        await self._async_discover_account_id()
        return self._account_id

    async def _async_fetch_csrf(self) -> None:
        """Get CSRF token and initial session cookie from login page."""
        try:
            async with async_timeout.timeout(10):
                resp = await self._session.get(
                    LOGIN_URL,
                    cookies={"accepted_cookies": "true"},
                )
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                "Timeout fetching login page"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error fetching login page: {exc}"
            ) from exc

        if resp.status != 200:
            raise One2TrackApiClientCommunicationError(
                f"Login page returned {resp.status}"
            )
        html = await resp.text()
        self._csrf = self._parse_csrf(html)
        cookie, name = self._parse_cookie(resp)
        self._cookie = cookie
        if name:
            self._cookie_name = name

    async def _async_login(self) -> None:
        """Submit login form."""
        data = {
            "authenticity_token": self._csrf,
            "user[login]": self._username,
            "user[password]": self._password,
            "gdpr": "1",
            "user[remember_me]": "1",
        }
        try:
            async with async_timeout.timeout(10):
                resp = await self._session.post(
                    LOGIN_URL,
                    data=data,
                    headers={"content-type": "application/x-www-form-urlencoded"},
                    cookies=self._cookies(),
                    allow_redirects=False,
                )
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                "Timeout during login"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error during login: {exc}"
            ) from exc

        if resp.status == 302 and "Set-Cookie" in resp.headers:
            cookie, name = self._parse_cookie(resp)
            if name:
                self._cookie_name = name
            self._cookie = cookie
            if not self._cookie:
                raise One2TrackApiClientAuthenticationError(
                    "Login succeeded but session cookie not found in response"
                )
        else:
            raise One2TrackApiClientAuthenticationError(
                "Invalid username or password"
            )

    async def _async_discover_account_id(self) -> None:
        """Follow redirect from base URL to discover account ID."""
        try:
            async with async_timeout.timeout(10):
                resp = await self._session.get(
                    BASE_URL + "/",
                    cookies=self._cookies(),
                    allow_redirects=False,
                )
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                "Timeout discovering account"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error discovering account: {exc}"
            ) from exc

        if resp.status == 302 and "Location" in resp.headers:
            location = resp.headers["Location"]
            parsed = urlparse(location)
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) >= 2:
                self._account_id = path_parts[1]
                return
        raise One2TrackApiClientAuthenticationError(
            "Could not discover account ID after login"
        )

    async def _async_ensure_authenticated(self) -> None:
        """Re-authenticate if session is missing."""
        if not self._cookie:
            await self.async_authenticate()

    async def _async_refresh_csrf(self) -> str:
        """Get a fresh CSRF token from login page."""
        try:
            async with async_timeout.timeout(10):
                resp = await self._session.get(LOGIN_URL, cookies=self._cookies())
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                "Timeout refreshing CSRF"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error refreshing CSRF: {exc}"
            ) from exc

        if resp.status != 200:
            raise One2TrackApiClientAuthenticationError(
                "Could not refresh CSRF token"
            )
        html = await resp.text()
        cookie, name = self._parse_cookie(resp)
        if cookie:
            self._cookie = cookie
        if name:
            self._cookie_name = name
        self._csrf = self._parse_csrf(html)
        return self._csrf

    # ── Device Discovery ────────────────────────────────────────────

    async def async_discover_devices(self) -> list[dict[str, Any]]:
        """Discover devices via JSON endpoint.

        Returns list of device dicts with uuid, name, serial_number, etc.
        """
        await self._async_ensure_authenticated()
        url = f"{BASE_URL}/users/{self._account_id}/devices"

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "content-type": "application/json",
                    },
                    cookies=self._cookies(),
                )
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                "Timeout fetching device list"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error fetching device list: {exc}"
            ) from exc

        if resp.status in (401, 302):
            self._cookie = ""
            raise One2TrackApiClientAuthenticationError(
                f"Device list returned {resp.status}"
            )
        if resp.status != 200:
            raise One2TrackApiClientCommunicationError(
                f"Device list returned {resp.status}"
            )

        body = await resp.text()
        if not body or body.lstrip().startswith(("<", "<!DOCTYPE")):
            self._cookie = ""
            raise One2TrackApiClientAuthenticationError(
                "Device list returned HTML instead of JSON — session likely expired"
            )

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Device list returned invalid JSON: {body[:200]}"
            ) from exc

        try:
            devices = [item["device"] for item in data]
            self._device_uuids = [d["uuid"] for d in devices]
        except (KeyError, TypeError) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Unexpected device list structure: {exc}"
            ) from exc
        return devices

    # ── Capability Discovery ────────────────────────────────────────

    async def async_discover_capabilities(self, uuid: str) -> dict[str, Any]:
        """Discover available commands for a device.

        Fetches GET /devices/{uuid}/functions?list_only=true and parses
        the HTML for function links.

        Returns:
            {
                "functions": {"0001": "SOS nummer", "0078": "GPS tracking", ...},
                "options": {"0078": [{"value": "300", "label": "...", "checked": False}]}
            }
        """
        await self._async_ensure_authenticated()
        url = f"{BASE_URL}/devices/{uuid}/functions?list_only=true"

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.get(url, cookies=self._cookies())
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                f"Timeout discovering capabilities for {uuid}"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error discovering capabilities for {uuid}: {exc}"
            ) from exc

        if resp.status in (401, 302):
            self._cookie = ""
            raise One2TrackApiClientAuthenticationError("Session expired")
        if resp.status != 200:
            LOGGER.warning(
                "Capability discovery for %s returned %s, skipping",
                uuid, resp.status,
            )
            return {"functions": {}, "options": {}}

        html = await resp.text()
        functions = self._parse_functions_list(html)
        LOGGER.debug(
            "Discovered %d functions for %s: %s",
            len(functions), uuid, list(functions.keys()),
        )
        return {"functions": functions, "options": {}}

    async def async_discover_command_options(
        self, uuid: str, cmd_code: str
    ) -> list[dict[str, Any]]:
        """Discover radio-button options for a specific command.

        Fetches GET /devices/{uuid}/functions?function={code}&list_only=true&modal=true
        and parses radio inputs + labels.

        Returns list of {"value": "300", "label": "Every 5 min...", "checked": bool}
        """
        await self._async_ensure_authenticated()
        url = (
            f"{BASE_URL}/devices/{uuid}/functions"
            f"?function={cmd_code}&list_only=true&modal=true"
        )

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.get(url, cookies=self._cookies())
        except (TimeoutError, aiohttp.ClientError, socket.gaierror) as exc:
            LOGGER.warning(
                "Could not discover options for cmd %s on %s: %s",
                cmd_code, uuid, exc,
            )
            return []

        if resp.status != 200:
            return []

        html = await resp.text()
        options = self._parse_command_options(html)
        LOGGER.debug(
            "Discovered %d options for cmd %s on %s: %s",
            len(options), cmd_code, uuid, options,
        )
        return options

    @staticmethod
    def _parse_functions_list(html: str) -> dict[str, str]:
        """Parse function links from the functions list HTML.

        Looks for <a href="...?function=XXXX...">Label</a> patterns.
        """
        functions: dict[str, str] = {}
        for match in re.finditer(
            r'href="[^"]*function=(\d+)[^"]*"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        ):
            code = match.group(1)
            label = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            label = unescape(label)
            functions[code] = label
        return functions

    @staticmethod
    def _parse_command_options(html: str) -> list[dict[str, Any]]:
        """Parse radio inputs from a command options modal.

        Looks for <input type="radio" name="function[cmd_value][]" value="X">
        followed by <label>text</label>.
        """
        options: list[dict[str, Any]] = []
        # Find all radio inputs with their values and checked state
        radios = re.findall(
            r'<input[^>]*type="radio"[^>]*name="function\[cmd_value\]\[\]"'
            r'[^>]*value="([^"]*)"([^>]*)>',
            html,
        )
        # Find all labels (same order as radios)
        labels = re.findall(r"<label[^>]*>(.*?)</label>", html, re.DOTALL)

        for i, (value, attrs) in enumerate(radios):
            label = ""
            if i < len(labels):
                label = re.sub(r"<[^>]+>", "", labels[i]).strip()
                label = unescape(label)
                # Normalize whitespace — scraped labels may contain \n and
                # other whitespace artifacts from the HTML layout
                label = re.sub(r"\s+", " ", label).strip()
            checked = "checked" in attrs
            options.append({"value": value, "label": label, "checked": checked})

        return options

    # ── Setting readback (fetch current form values) ─────────────────

    async def async_fetch_form_values(
        self, uuid: str, cmd_code: str
    ) -> list[str]:
        """Fetch current form input values for a command.

        Fetches the function form page and extracts all
        <input name="function[cmd_value][]" value="..."> values,
        regardless of input type (text, hidden, tel, etc.).
        Returns the list of values in page order.
        """
        await self._async_ensure_authenticated()
        url = (
            f"{BASE_URL}/devices/{uuid}/functions"
            f"?function={cmd_code}&list_only=true&modal=true"
        )

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.get(url, cookies=self._cookies())
        except (TimeoutError, aiohttp.ClientError, socket.gaierror) as exc:
            LOGGER.debug(
                "Could not fetch form values for cmd %s on %s: %s",
                cmd_code, uuid, exc,
            )
            return []

        if resp.status != 200:
            return []

        html = await resp.text()
        return self._parse_form_values(html)

    @staticmethod
    def _parse_form_values(html: str) -> list[str]:
        """Extract all cmd_value input values from a function form page.

        Matches <input ... name="function[cmd_value][]" value="X" ...>
        for any input type (text, hidden, tel, etc.).
        """
        return re.findall(
            r'<input[^>]*name="function\[cmd_value\]\[\]"'
            r'[^>]*value="([^"]*)"',
            html,
        )

    # ── Device State (HTML scraping) ────────────────────────────────

    async def async_get_device_state(self, uuid: str) -> dict[str, Any]:
        """Fetch rich device state by scraping the per-device HTML page.

        Returns a dict with 'device' and 'last_location' keys.
        """
        await self._async_ensure_authenticated()
        url = f"{BASE_URL}/devices/{uuid}"

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.get(url, cookies=self._cookies())
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                f"Timeout fetching device {uuid}"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error fetching device {uuid}: {exc}"
            ) from exc

        if resp.status in (401, 302):
            self._cookie = ""
            raise One2TrackApiClientAuthenticationError("Session expired")
        if resp.status != 200:
            raise One2TrackApiClientCommunicationError(
                f"Device page for {uuid} returned {resp.status}"
            )

        html = await resp.text()
        return self._parse_device_page(html, uuid)

    def _parse_device_page(self, html: str, uuid: str) -> dict[str, Any]:
        """Extract device and last_location from inline JS vars.

        Uses raw_decode to properly handle nested JSON objects (the old
        non-greedy regex stopped at the first '}', breaking on nested
        objects like meta_data).
        """
        result: dict[str, Any] = {}
        decoder = json.JSONDecoder()

        device_match = re.search(r"var device\s*=\s*", html)
        if device_match:
            try:
                result["device"], _ = decoder.raw_decode(html, device_match.end())
            except (json.JSONDecodeError, ValueError):
                LOGGER.debug("Could not parse 'var device' JSON for %s", uuid)

        location_match = re.search(r"var last_location\s*=\s*", html)
        if location_match:
            try:
                result["last_location"], _ = decoder.raw_decode(
                    html, location_match.end()
                )
            except (json.JSONDecodeError, ValueError):
                LOGGER.debug(
                    "Could not parse 'var last_location' JSON for %s", uuid
                )

        if not result:
            LOGGER.warning(
                "HTML scraping returned no data for %s — page structure may have changed",
                uuid,
            )

        return result

    async def async_get_all_device_states(self) -> dict[str, dict[str, Any]]:
        """Fetch state for all known devices. Returns {uuid: state_dict}."""
        await self._async_ensure_authenticated()

        if not self._device_uuids:
            await self.async_discover_devices()

        states: dict[str, dict[str, Any]] = {}
        for uuid in self._device_uuids:
            try:
                state = await self.async_get_device_state(uuid)
                if state:
                    states[uuid] = state
            except One2TrackApiClientAuthenticationError:
                await self.async_authenticate()
                state = await self.async_get_device_state(uuid)
                if state:
                    states[uuid] = state

        return states

    # ── Commands (settings & actions) ───────────────────────────────

    async def async_send_command(
        self,
        uuid: str,
        cmd_code: str,
        cmd_values: list[str] | None = None,
    ) -> bool:
        """Send a command to a device.

        Uses PATCH /devices/{uuid}/functions (Rails form convention).
        Body: _method=patch, authenticity_token, function[cmd_code],
              function[cmd_value][] (repeated for each value).
        """
        await self._async_ensure_authenticated()
        csrf = await self._async_refresh_csrf()

        url = f"{BASE_URL}/devices/{uuid}/functions"

        # Build form data as list of tuples to allow repeated keys
        form_data: list[tuple[str, str]] = [
            ("utf8", "\u2713"),
            ("_method", "patch"),
            ("authenticity_token", csrf),
            ("function[cmd_code]", cmd_code),
        ]
        if cmd_values:
            for val in cmd_values:
                form_data.append(("function[cmd_value][]", val))

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.post(
                    url,
                    data=form_data,
                    headers={
                        "x-csrf-token": csrf,
                        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    },
                    cookies=self._cookies(),
                )
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                f"Timeout sending command {cmd_code} to {uuid}"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error sending command {cmd_code} to {uuid}: {exc}"
            ) from exc

        return resp.status == 200

    # ── Messages ────────────────────────────────────────────────────

    async def async_send_message(self, uuid: str, message: str) -> bool:
        """Send a text message to a device."""
        await self._async_ensure_authenticated()
        csrf = await self._async_refresh_csrf()

        url = f"{BASE_URL}/devices/{uuid}/messages"
        data = {
            "utf8": "\u2713",
            "authenticity_token": csrf,
            "device_message[message]": message,
        }
        headers = {
            "x-csrf-token": csrf,
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "accept": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml",
        }

        try:
            async with async_timeout.timeout(15):
                resp = await self._session.post(
                    url, data=data, headers=headers, cookies=self._cookies()
                )
        except TimeoutError as exc:
            raise One2TrackApiClientCommunicationError(
                f"Timeout sending message to {uuid}"
            ) from exc
        except (aiohttp.ClientError, socket.gaierror) as exc:
            raise One2TrackApiClientCommunicationError(
                f"Error sending message to {uuid}: {exc}"
            ) from exc

        return resp.status == 200

    # ── Raw data (for diagnostics / testing) ───────────────────────

    async def async_get_raw_device_data(self, uuid: str) -> dict[str, Any]:
        """Fetch raw live data for a device from all sources."""
        await self._async_ensure_authenticated()

        result: dict[str, Any] = {"account_id": self._account_id}

        # 1. Fresh JSON from the device list endpoint
        try:
            url = f"{BASE_URL}/users/{self._account_id}/devices"
            async with async_timeout.timeout(15):
                resp = await self._session.get(
                    url,
                    headers={"Accept": "application/json", "content-type": "application/json"},
                    cookies=self._cookies(),
                )
            if resp.status == 200:
                body = await resp.text()
                if body and not body.lstrip().startswith(("<", "<!DOCTYPE")):
                    data = json.loads(body)
                    for item in data:
                        dev = item.get("device", {})
                        if dev.get("uuid") == uuid:
                            result["json_api"] = item
                            break
        except Exception as exc:  # noqa: BLE001
            result["json_api_error"] = str(exc)

        # 2. HTML-scraped data from the device page
        try:
            state = await self.async_get_device_state(uuid)
            result["html_scraped"] = state
        except Exception as exc:  # noqa: BLE001
            result["html_scraped_error"] = str(exc)

        # 3. Discovered capabilities (with options for radio commands)
        try:
            from .const import RADIO_COMMANDS

            caps = await self.async_discover_capabilities(uuid)
            functions = caps.get("functions", {})
            options: dict[str, list] = {}
            for code in RADIO_COMMANDS:
                if code in functions:
                    opts = await self.async_discover_command_options(uuid, code)
                    if opts:
                        options[code] = opts
            caps["options"] = options
            result["capabilities"] = caps
        except Exception as exc:  # noqa: BLE001
            result["capabilities_error"] = str(exc)

        return result

    # ── Helpers ─────────────────────────────────────────────────────

    def _cookies(self) -> dict[str, str]:
        cookies = {"accepted_cookies": "true"}
        if self._cookie:
            cookies[self._cookie_name] = self._cookie
        return cookies

    @staticmethod
    def _parse_csrf(html: str) -> str:
        match = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
        if match:
            return match.group(1)
        match = re.search(r'name="authenticity_token"[^>]+value="([^"]+)"', html)
        if match:
            return match.group(1)
        raise One2TrackApiClientAuthenticationError("CSRF token not found")

    @staticmethod
    def _parse_cookie(response: aiohttp.ClientResponse) -> tuple[str, str]:
        """Parse session cookie from response.

        Checks for both _iadmin and _session_id cookie names.
        Returns (cookie_value, cookie_name) or ("", "") if not found.
        """
        for cookie_name in (SESSION_COOKIE, SESSION_COOKIE_ALT):
            for set_cookie in response.headers.getall("Set-Cookie", []):
                if cookie_name in set_cookie:
                    part = set_cookie.split(cookie_name + "=")[1]
                    return part.split(";")[0], cookie_name
        return "", ""
