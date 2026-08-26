from __future__ import annotations

import time

import requests
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

from .config import LMS_BASE, PAGE_TIMEOUT


def create_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--lang=vi-VN")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(PAGE_TIMEOUT)
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
