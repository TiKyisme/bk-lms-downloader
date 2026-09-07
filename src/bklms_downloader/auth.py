from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.selenium_manager import SeleniumManager
from selenium.webdriver.support.ui import WebDriverWait

from .config import LMS_BASE, PAGE_TIMEOUT


def create_driver(timing: Callable[[str, float], None] | None = None) -> webdriver.Chrome:
    started = time.perf_counter()
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--lang=vi-VN")
    if timing:
        timing("options", time.perf_counter() - started)
    service = Service()
    started = time.perf_counter()
    # Resolve once using Selenium's version-aware cache, then pass the result
    # to Service. No fixed driver, custom PATH search, or background prewarming.
    if not service.path:
        paths = SeleniumManager().binary_paths(["--browser", "chrome", "--avoid-stats"])
        if not Path(paths["driver_path"]).is_file() or not Path(paths["browser_path"]).is_file():
            raise RuntimeError("Selenium Manager did not return installed browser/driver files")
        service.path = paths["driver_path"]
        options.binary_location = paths["browser_path"]
    if timing:
        timing("driver_resolution", time.perf_counter() - started)
    started = time.perf_counter()
    driver = webdriver.Chrome(options=options, service=service)
    if timing:
        timing("driver_create", time.perf_counter() - started)
    try:
        driver.set_page_load_timeout(PAGE_TIMEOUT)
    except Exception:
        driver.quit()
        raise
    return driver


def wait_page(driver: webdriver.Chrome, extra: float = 0.8) -> None:
    WebDriverWait(driver, PAGE_TIMEOUT).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )
    time.sleep(extra)


def make_session(driver: webdriver.Chrome) -> requests.Session:
    session = requests.Session()
    try:
        session.headers["User-Agent"] = driver.execute_script("return navigator.userAgent")
    except Exception:
        pass

    session.headers.update({"Referer": LMS_BASE + "/", "Accept": "*/*"})
    for cookie in driver.get_cookies():
        session.cookies.set(
            cookie["name"], cookie["value"],
            domain=cookie.get("domain"), path=cookie.get("path", "/")
        )
    return session
