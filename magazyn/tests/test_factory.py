from magazyn.config import settings
from magazyn import db as db_mod
from magazyn import factory


def test_create_app_initializes_agent_and_migrations(tmp_path, monkeypatch, request):
    original_db_path = settings.DB_PATH
    tmp_db_path = tmp_path / "app.db"
    monkeypatch.setattr(settings, "DB_PATH", str(tmp_db_path))

    db_mod.configure_engine(settings.DB_PATH)
    request.addfinalizer(lambda: db_mod.configure_engine(original_db_path))

    migrations_called = []

    def fake_apply_migrations():
        migrations_called.append(True)

    monkeypatch.setattr(db_mod, "apply_migrations", fake_apply_migrations)

    call_order = []
    original_ensure = factory.ensure_db_initialized

    def tracking_ensure(app_obj=None):
        call_order.append(("ensure", app_obj))
        original_ensure(app_obj)

    monkeypatch.setattr(factory, "ensure_db_initialized", tracking_ensure)

    def fake_start_agent(app_obj=None):
        call_order.append(("start", app_obj))

    monkeypatch.setattr(factory, "start_print_agent", fake_start_agent)

    app = factory.create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})

    assert migrations_called, "Migrations should run during app creation"
    assert ("ensure", app) in call_order, "Database init should be triggered immediately"
    assert ("start", app) in call_order, "Agent should start during app creation"
    assert call_order.index(("ensure", app)) < call_order.index(("start", app))
