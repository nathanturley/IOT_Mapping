import logging
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

from iot_mapping.config import THINGSBOARD_DASHBOARD_URL

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def get_offline_nodes(
    url: str,
    wait_time: int = 5,
    headless: bool = True,
) -> list[tuple[str, str]]:
    """
    Scrape a ThingsBoard dashboard for offline nodes.

    Returns a list of (name, node_id) tuples for each offline device.
    """
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(30)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver.get(url)
            break
        except TimeoutException:
            if attempt == MAX_RETRIES:
                logger.error("Failed to load page after %d attempts", MAX_RETRIES)
                return []
            logger.warning("Timeout loading page, retrying (%d/%d)...", attempt, MAX_RETRIES)

    try:
        logger.info("Waiting %d seconds for page to render...", wait_time)
        time.sleep(wait_time)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        results = []

        offline_blocks = soup.find_all("div", class_="n_value")
        logger.debug("Found %d status blocks", len(offline_blocks))

        for block in offline_blocks:
            status_text = block.get_text(strip=True)
            if status_text != "Offline":
                continue

            card = block.find_parent("div", class_="n_card")
            if not card:
                logger.warning("Could not find parent card for offline block")
                continue

            name_elem = card.find("div", class_="m_content")
            name = name_elem.contents[0].strip() if name_elem and name_elem.contents else "Unknown"

            small = card.find("div", class_="n2_valueSmall")
            if not small:
                logger.warning("Could not find node ID for %s", name)
                continue

            text = small.get_text(" ", strip=True)
            if "Node ID:" in text:
                node_id = text.split("Node ID:")[1].split("Type:")[0].strip()
            else:
                node_id = "Unknown"

            results.append((name, node_id))
            logger.info("Found offline node: %s (%s)", name, node_id)

        logger.info("Total offline nodes found: %d", len(results))
        return results

    finally:
        driver.quit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    offline_nodes = get_offline_nodes(THINGSBOARD_DASHBOARD_URL)
    for name, nid in offline_nodes:
        print(f"{name}, {nid}")


if __name__ == "__main__":
    main()
