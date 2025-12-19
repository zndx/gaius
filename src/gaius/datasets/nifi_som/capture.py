"""Screenshot capture for NiFi canvas using Selenium.

Uses Selenium with chromium/chromedriver from nixpkgs to avoid GLIBC conflicts
that occur with Playwright's bundled Node.js driver in nix environments.
"""

import io
import shutil
import time
from pathlib import Path
from typing import Optional

from PIL import Image

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


def _find_chromedriver() -> Optional[str]:
    """Find chromedriver binary from PATH (nixpkgs provides it)."""
    return shutil.which("chromedriver")


def _find_chromium() -> Optional[str]:
    """Find chromium binary from PATH (nixpkgs provides it)."""
    # Try common names
    for name in ["chromium", "chromium-browser", "google-chrome"]:
        path = shutil.which(name)
        if path:
            return path
    return None


class NiFiScreenshotCapture:
    """Capture screenshots of NiFi canvas using Selenium."""

    def __init__(
        self,
        nifi_url: str = "http://localhost:8450",
        viewport_width: int = 1920,
        viewport_height: int = 1080,
    ):
        self.nifi_url = nifi_url.rstrip("/")
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self._driver: Optional[webdriver.Chrome] = None

    async def __aenter__(self):
        """Async context manager entry - creates browser synchronously."""
        if not SELENIUM_AVAILABLE:
            raise ImportError(
                "Selenium is required for screenshot capture. "
                "Install with: uv sync --extra dataset"
            )

        chromedriver_path = _find_chromedriver()
        chromium_path = _find_chromium()

        if not chromedriver_path:
            raise RuntimeError(
                "chromedriver not found in PATH. "
                "Add 'chromedriver' to devenv.nix packages."
            )

        if not chromium_path:
            raise RuntimeError(
                "chromium not found in PATH. "
                "Add 'chromium' to devenv.nix packages."
            )

        # Configure Chrome options
        options = Options()
        options.add_argument("--headless=new")  # Use new headless mode
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"--window-size={self.viewport_width},{self.viewport_height}")
        options.binary_location = chromium_path

        # Create service with chromedriver
        service = Service(executable_path=chromedriver_path)

        # Create the driver
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.set_window_size(self.viewport_width, self.viewport_height)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._driver:
            self._driver.quit()
            self._driver = None

    async def capture_canvas(
        self,
        process_group_id: str,
        wait_selector: str = ".processor",
        wait_timeout: int = 10,
    ) -> Image.Image:
        """Capture a screenshot of a NiFi process group canvas.

        Args:
            process_group_id: The NiFi process group ID to capture
            wait_selector: CSS selector to wait for before capture
            wait_timeout: Timeout in seconds to wait for selector

        Returns:
            PIL Image of the canvas
        """
        if not self._driver:
            raise RuntimeError("Must use as async context manager")

        # Navigate to the NiFi canvas for this process group
        url = f"{self.nifi_url}/nifi/?processGroupId={process_group_id}"
        self._driver.get(url)

        # Wait for canvas to load
        try:
            wait = WebDriverWait(self._driver, wait_timeout)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector)))
        except Exception:
            # Fall back to waiting for page to be ready
            time.sleep(2)  # Extra time for rendering

        # Capture screenshot
        screenshot_bytes = self._driver.get_screenshot_as_png()
        return Image.open(io.BytesIO(screenshot_bytes))

    async def capture_to_file(
        self,
        process_group_id: str,
        output_path: Path,
        wait_selector: str = ".processor",
    ) -> Path:
        """Capture and save a screenshot to a file.

        Args:
            process_group_id: The NiFi process group ID to capture
            output_path: Path to save the screenshot
            wait_selector: CSS selector to wait for before capture

        Returns:
            Path to the saved screenshot
        """
        image = await self.capture_canvas(process_group_id, wait_selector)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG")
        return output_path


async def capture_screenshot(
    process_group_id: str,
    nifi_url: str = "http://localhost:8450",
    output_path: Optional[Path] = None,
) -> Image.Image:
    """Convenience function to capture a single screenshot.

    Args:
        process_group_id: NiFi process group ID
        nifi_url: NiFi base URL
        output_path: Optional path to save the screenshot

    Returns:
        PIL Image of the canvas
    """
    async with NiFiScreenshotCapture(nifi_url) as capture:
        image = await capture.capture_canvas(process_group_id)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "PNG")
        return image


class NiFiInteractionCapture(NiFiScreenshotCapture):
    """Capture screenshots while executing interactions on NiFi canvas.

    Extends NiFiScreenshotCapture with the ability to execute actions
    (click, drag, etc.) and capture frames for Trace-of-Mark datasets.
    """

    async def capture_interaction_sequence(
        self,
        process_group_id: str,
        actions: list[dict],
        capture_before: bool = True,
        capture_after_each: bool = True,
        wait_between_ms: int = 500,
    ) -> list[Image.Image]:
        """Execute a sequence of actions and capture frames.

        Args:
            process_group_id: The NiFi process group ID
            actions: List of action dicts with 'type' and 'coordinates'
            capture_before: Capture initial state before any action
            capture_after_each: Capture after each action
            wait_between_ms: Delay between actions in ms

        Returns:
            List of captured frames
        """
        if not self._driver:
            raise RuntimeError("Must use as async context manager")

        frames = []

        # Navigate to canvas
        url = f"{self.nifi_url}/nifi/?processGroupId={process_group_id}"
        self._driver.get(url)
        time.sleep(2)  # Wait for page to load

        # Capture initial state
        if capture_before:
            frames.append(self._capture_frame())

        # Execute each action and capture
        for action in actions:
            self._execute_action(action)
            time.sleep(wait_between_ms / 1000)

            if capture_after_each:
                frames.append(self._capture_frame())

        return frames

    def _capture_frame(self) -> Image.Image:
        """Capture a single frame from the current page state."""
        screenshot_bytes = self._driver.get_screenshot_as_png()
        return Image.open(io.BytesIO(screenshot_bytes))

    def _execute_action(self, action: dict):
        """Execute a single action on the page.

        Args:
            action: Dict with 'type', 'coordinates' (normalized 0-1)
        """
        action_type = action.get("type", "click")
        coords = action.get("coordinates", (0.5, 0.5))

        # Convert normalized coordinates to pixels
        x = int(coords[0] * self.viewport_width)
        y = int(coords[1] * self.viewport_height)

        # Create action chain for complex actions
        actions = ActionChains(self._driver)

        if action_type == "click":
            # Move to position relative to body, then click
            body = self._driver.find_element(By.TAG_NAME, "body")
            actions.move_to_element_with_offset(body, x - self.viewport_width // 2, y - self.viewport_height // 2)
            actions.click()
            actions.perform()
        elif action_type == "double_click":
            body = self._driver.find_element(By.TAG_NAME, "body")
            actions.move_to_element_with_offset(body, x - self.viewport_width // 2, y - self.viewport_height // 2)
            actions.double_click()
            actions.perform()
        elif action_type == "drag":
            # Drag requires end coordinates
            end_coords = action.get("end_coordinates", coords)
            end_x = int(end_coords[0] * self.viewport_width)
            end_y = int(end_coords[1] * self.viewport_height)
            body = self._driver.find_element(By.TAG_NAME, "body")
            # Calculate relative offsets from center
            start_offset_x = x - self.viewport_width // 2
            start_offset_y = y - self.viewport_height // 2
            end_offset_x = end_x - self.viewport_width // 2
            end_offset_y = end_y - self.viewport_height // 2
            # Move to start, click and drag to end
            actions.move_to_element_with_offset(body, start_offset_x, start_offset_y)
            actions.click_and_hold()
            actions.move_to_element_with_offset(body, end_offset_x, end_offset_y)
            actions.release()
            actions.perform()
        elif action_type == "hover":
            body = self._driver.find_element(By.TAG_NAME, "body")
            actions.move_to_element_with_offset(body, x - self.viewport_width // 2, y - self.viewport_height // 2)
            actions.perform()


async def capture_interaction_sequence(
    process_group_id: str,
    actions: list[dict],
    nifi_url: str = "http://localhost:8450",
) -> list[Image.Image]:
    """Convenience function to capture an interaction sequence.

    Args:
        process_group_id: NiFi process group ID
        actions: List of action dicts
        nifi_url: NiFi base URL

    Returns:
        List of captured frames
    """
    async with NiFiInteractionCapture(nifi_url) as capture:
        return await capture.capture_interaction_sequence(process_group_id, actions)
