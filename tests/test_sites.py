"""Site profiles: which saved login a URL belongs to, and what a login page looks like."""

from pathlib import Path

from assistant.sites import SITES, looks_like_login, session_path, site_for_url


def test_every_configured_site_is_recognised_by_host():
    assert site_for_url("https://www.gradescope.com/courses/123").key == "gradescope"
    assert site_for_url("https://paperless.stanford.edu/assignments").key == "paperless"
    assert site_for_url("https://us.edstem.org/courses/1/discussion").key == "ed"
    assert site_for_url("https://canvas.stanford.edu/courses/231533/pages/lab-logistics").key == "canvas"
    assert site_for_url("https://example.com/") is None
    assert set(SITES) == {"gradescope", "paperless", "ed", "canvas"}


def test_login_pages_are_detected_including_stanford_sso_hops():
    gs = SITES["gradescope"]
    assert looks_like_login("https://www.gradescope.com/login", gs)
    assert looks_like_login("https://login.stanford.edu/idp/profile/SAML2/Redirect/SSO?x=1", gs)
    assert looks_like_login("https://idp.stanford.edu/idp/profile/SAML2/POST/SSO", gs)
    assert not looks_like_login("https://www.gradescope.com/courses/123", gs)
    assert looks_like_login("https://api-8e28xxx.duosecurity.com/frame/v4/auth", gs)   # Duo prompt mid-login


def test_session_files_live_under_data_browser():
    assert session_path(Path("/opt/juno/data"), SITES["gradescope"]) == Path("/opt/juno/data/browser/gradescope.json")
