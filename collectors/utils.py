import requests
from bs4 import BeautifulSoup

_URL_CACHE = {}


def soup(s: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page (cached by URL)."""
    if url in _URL_CACHE:
        return BeautifulSoup(_URL_CACHE[url], "html.parser")
    r = None
    for _ in range(5):
        try:
            r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
            r.raise_for_status()
            break
        except (requests.RequestException, requests.Timeout):
            continue
    if r is not None:
        _URL_CACHE[url] = r.text
        return BeautifulSoup(r.text, "html.parser")
    else:
        return BeautifulSoup("", "html.parser")
