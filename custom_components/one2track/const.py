"""Constants for the One2Track integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__name__)

DOMAIN = "one2track"

DEFAULT_UPDATE_INTERVAL_SECONDS = 60

BASE_URL = "https://www.one2trackgps.com"
LOGIN_URL = f"{BASE_URL}/auth/users/sign_in"
SESSION_COOKIE = "_iadmin"
# The portal may also use "_session_id" on some deployments; we check both.
SESSION_COOKIE_ALT = "_session_id"

# ── Command codes — actions (universal, all models) ──────────────
CMD_REFRESH_LOCATION = "0039"
CMD_FIND_DEVICE = "1015"

# ── Command codes — settings (universal, all models) ─────────────
CMD_SOS_NUMBER = "0001"
CMD_FACTORY_RESET = "0011"
CMD_REMOTE_SHUTDOWN = "0048"
CMD_ALARMS = "0057"
CMD_LANGUAGE_TIMEZONE = "0124"
CMD_QUIET_TIMES = "1107"
CMD_PHONEBOOK = "1315"

# ── Command codes — model-specific ───────────────────────────────
# These differ per watch model. The integration discovers which code
# each device actually supports at init time.
CMD_INTERCOM = "0084"           # Connect MOVE only
CMD_CHANGE_PASSWORD = "0067"    # Connect MOVE only
CMD_WHITELIST_1 = "0080"        # Connect MOVE only
CMD_WHITELIST_2 = "0081"        # Connect MOVE only

# GPS interval: MOVE uses 0078, UP uses 0077
GPS_INTERVAL_CODES = ("0077", "0078")
# Step counter: MOVE uses 0079, UP uses 0082
STEP_COUNTER_CODES = ("0079", "0082")
# Profile/scene mode
CMD_PROFILE_MODE = "1116"

# ── Candidate codes for settings readback ────────────────────────
# Used by the coordinator to discover which code each device uses.
# If a future model uses a different code, add it to the tuple.
PHONEBOOK_CODES = (CMD_PHONEBOOK,)
ALARM_CODES = (CMD_ALARMS,)
QUIET_TIMES_CODES = (CMD_QUIET_TIMES,)
# Whitelist: pairs of (slot1, slot2) codes — MOVE uses 0080+0081
WHITELIST_SLOT_CODES = ((CMD_WHITELIST_1, CMD_WHITELIST_2),)

# Commands whose options should be discovered dynamically from the portal
# (radio button forms that vary per model/firmware)
RADIO_COMMANDS = GPS_INTERVAL_CODES + (CMD_PROFILE_MODE,)

# Fallback options (only used if dynamic discovery fails)
GPS_INTERVAL_OPTIONS_FALLBACK = {
    "10": "10 seconds (high battery usage)",
    "300": "5 minutes (medium battery usage)",
    "600": "10 minutes (low battery usage)",
}

PROFILE_MODE_OPTIONS_FALLBACK = {
    "1": "Vibrate & Sound",
    "2": "Sound only",
    "3": "Vibrate only",
    "4": "Silent",
}
