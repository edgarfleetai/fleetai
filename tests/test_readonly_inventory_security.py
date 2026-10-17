from fleetai.admin_policy import requires_owner


def test_readonly_inventory_requires_owner():
    assert requires_owner("/api/overview-readonly", "GET")
    assert not requires_owner("/api/overview-readonly", "POST")


def test_readonly_inventory_anonymous_denied():
    from fleetai import create_app
    app = create_app()
    app.testing = True
    with app.test_client() as client:
        response = client.get("/api/overview-readonly")
    assert response.status_code == 401
    assert response.get_json()["ok"] is False
    assert response.headers["Cache-Control"] == "no-store"
