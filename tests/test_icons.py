from fastapi.testclient import TestClient

from sklent.app import app


def test_root_icons_are_images_not_the_spa():
    c = TestClient(app)
    for path, ctype in [
        ("/favicon.ico", "image/"),
        ("/favicon.svg", "image/svg+xml"),
        ("/apple-touch-icon.png", "image/png"),
        ("/apple-touch-icon-precomposed.png", "image/png"),
    ]:
        r = c.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(ctype), path
    assert c.get("/anything").headers["content-type"].startswith("text/html")
