"""Route-sweep (M9): every non-auth API route must reject an unauthenticated
request. Enumerated via `app.openapi()` rather than walking `app.routes`
directly — this FastAPI version resolves included routers lazily, so the
OpenAPI schema (which FastAPI must fully flatten to serve `/docs`) is the
one reliably version-agnostic source of every registered path+method.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.integration

# (method, path-template) pairs that must NOT require a session.
EXEMPT = {
    ("get", "/api/health"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/logout"),
}

_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _dummy_path(template: str) -> str:
    """Replace every `{param}` with a valid-looking scalar so a 422 (bad
    path type) never masks the 401 this test is checking for."""
    return _PATH_PARAM.sub("1", template)


def _all_routes() -> list[tuple[str, str]]:
    schema = app.openapi()
    return [
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    ]


@pytest.mark.parametrize("method,path", _all_routes())
def test_route_rejects_unauthenticated_access(
    anon_client: TestClient, method: str, path: str
) -> None:
    if (method, path) in EXEMPT:
        pytest.skip("exempt route — covered by test_auth.py")
    response = anon_client.request(method, _dummy_path(path))
    assert response.status_code == 401, f"{method.upper()} {path} returned {response.status_code}"


def test_every_route_is_accounted_for() -> None:
    """Guards against the sweep silently shrinking (e.g. a future FastAPI
    version changing how `openapi()` reports paths) — fails loud if the
    route count drops far below what M1-M9 actually registers."""
    routes = _all_routes()
    assert len(routes) >= 40
    for method, path in EXEMPT:
        assert (method, path) in routes, f"exempt route {method} {path} no longer registered"
