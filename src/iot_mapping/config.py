from zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")

THINGSBOARD_DASHBOARD_URL = (
    "https://live2.innovateauckland.nz/dashboard/"
    "baafc030-dfa9-11ec-bc22-bb13277b57e1"
    "?publicId=8d688430-d497-11ec-92a2-f938b249c783"
)

DEFAULT_ZOOM = 9
CI_SCRAPER_WAIT = 10
LOCAL_SCRAPER_WAIT = 5

MARKER_STYLES = {
    "gateway":  {"icon": "cloud",    "color": "purple"},
    "repeater": {"icon": "exchange", "color": "pink"},
    "tank":     {"icon": "tint",     "color": "blue"},
    "stream":   {"icon": "tint",     "color": "green"},
    "default":  {"icon": "circle",   "color": "gray"},
}

OFFLINE_COLOR = "red"
