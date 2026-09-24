"""Sites juno can browse with a saved login, and how to tell a login page from a real one.

A saved login is a Playwright storage state file (cookies + local storage) that
you create once on your Mac with `uv run assistant browser-login <site>`. It's
deployed to the server and reused until the site logs juno out, at which point
juno tells you to run the command again. Stanford's Duo step is why juno can
never log in by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# URL fragments that mean "this is a login flow", including Stanford's SSO and Duo hops
GENERIC_LOGIN_MARKERS = (
    "login.stanford.edu", "idp.stanford.edu", "duosecurity.com", "weblogin",
    "/login", "/saml/", "/sso", "/auth/", "/signin", "/sign_in",
)


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    hosts: tuple[str, ...]
    login_url: str
    home_url: str
    login_markers: tuple[str, ...] = ()


SITES: dict[str, Site] = {
    "gradescope": Site("gradescope", "Gradescope", ("gradescope.com",), "https://www.gradescope.com/login", "https://www.gradescope.com/"),
    "paperless": Site("paperless", "Paperless (CS 106B)", ("paperless.stanford.edu", "cs198.stanford.edu"),
                      "https://paperless.stanford.edu/", "https://paperless.stanford.edu/"),
    "ed": Site("ed", "Ed Discussion", ("edstem.org",), "https://edstem.org/us/login", "https://edstem.org/us/dashboard"),
    "canvas": Site("canvas", "Canvas", ("canvas.stanford.edu",), "https://canvas.stanford.edu/login", "https://canvas.stanford.edu/"),
}


def site_for_url(url: str) -> Site | None:
    host = (urlparse(url).hostname or "").lower()
    for site in SITES.values():
        if any(host == h or host.endswith("." + h) for h in site.hosts):
            return site
    return None


def looks_like_login(url: str, site: Site | None = None) -> bool:
    lower = url.lower()
    markers = GENERIC_LOGIN_MARKERS + (site.login_markers if site else ())
    return any(m in lower for m in markers)


def session_path(data_dir: Path, site: Site) -> Path:
    return data_dir / "browser" / f"{site.key}.json"
