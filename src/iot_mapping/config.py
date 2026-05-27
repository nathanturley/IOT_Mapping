"""
Shared constants used across the iot_mapping package.
Edit this file to change URLs, map defaults, or marker appearance.
"""

from zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")

# Public dashboard URL — used by the scraper to check which nodes are offline
THINGSBOARD_DASHBOARD_URL = (
    "https://live2.innovateauckland.nz/dashboard/"
    "baafc030-dfa9-11ec-bc22-bb13277b57e1"
    "?publicId=8d688430-d497-11ec-92a2-f938b249c783"
)

DEFAULT_ZOOM = 9

# ThingsBoard dashboard is JS-rendered, so the scraper must wait for it to load.
# CI environments are slower, so they get a longer wait.
CI_SCRAPER_WAIT = 10
LOCAL_SCRAPER_WAIT = 5

# FontAwesome icon + Folium color for each device type.
# The key is matched as a substring of the device's Type field (case-insensitive).
MARKER_STYLES = {
    "gateway":  {"icon": "cloud",    "color": "purple"},
    "repeater": {"icon": "exchange", "color": "pink"},
    "tank":     {"icon": "tint",     "color": "blue"},
    "stream":   {"icon": "tint",     "color": "green"},
    "default":  {"icon": "circle",   "color": "gray"},
}

OFFLINE_COLOR = "red"
