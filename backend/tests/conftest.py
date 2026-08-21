"""
Test fixtures for Tally backend.
Uses an in-memory SQLite database — isolated per test session.

Concurrency tests use a separate stack — see ``race_client`` at the bottom of
this file — because the default ``db``/``client`` pair shares one Session
across threads, which is not what production does and not safe to race.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app import models
from app.auth import hash_password
from app import auth as _auth


@pytest.fixture(autouse=True)
def _reset_auth_rate_limits():
    """AUDIT-27: the in-process login/recover rate limiter keeps state across
    requests. Tests share one TestClient IP and log in many times, so reset the
    buckets before every test to avoid spurious 429s in unrelated tests."""
    _auth.reset_rate_limits()
    yield
    _auth.reset_rate_limits()

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def db_engine():
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def owner_token(client, db):
    """Seed an owner user and return a valid JWT."""
    # Seed role
    owner_role = models.Role(name="owner", display_name="Owner", is_system=True)
    db.add(owner_role)
    db.flush()

    # Seed analyst persona (required for User FK)
    persona = models.Persona(
        name="analyst",
        description="Test",
        data_access_level="full",
        can_modify_data=True,
        is_system=True,
    )
    db.add(persona)
    db.flush()

    user = models.User(
        username="testowner",
        hashed_password=hash_password("testpass"),
        role_id=owner_role.id,
        persona_id=persona.id,
    )
    db.add(user)
    db.commit()

    resp = client.post("/api/auth/login", json={"username": "testowner", "password": "testpass"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def auth_headers(owner_token):
    return {"Authorization": f"Bearer {owner_token}"}


@pytest.fixture()
def test_account(db, owner_token):
    """Return a seeded Account owned by the test owner."""
    user = db.query(models.User).filter(models.User.username == "testowner").first()
    account = models.Account(
        user_id=user.id,
        name="Test Cheque",
        account_type="checking",
        balance=1000.0,
        currency="AUD",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


SAMPLE_CSV = b"Date,Description,Amount\n2026-05-01,Coffee,-4.50\n2026-05-02,Salary,2000.00\n"


# ---------------------------------------------------------------------------
# Concurrency fixture stack (BACKLOG-050)
# ---------------------------------------------------------------------------
# The fixtures above give every request the SAME SQLAlchemy Session. A Session
# is not thread-safe, so racing two requests through it races the test harness
# rather than the endpoint, and the loser can surface a spurious error instead
# of the 409 the endpoint would really return.
#
# This stack reproduces production instead:
#   * a file-backed SQLite database, so two connections see the same data,
#   * a fresh Session per request, exactly like app.database.get_db,
#   * WAL journalling and a busy timeout, exactly like the running app, so a
#     writer that arrives second waits for the lock rather than erroring.
#
# With those in place the race has only two possible outcomes — whichever
# request wins the write lock commits, the other finds the draft already moved
# out of 'preview_ready' and gets a 409 — so the assertion holds under every
# thread interleaving rather than under lucky ones.

RACE_BUSY_TIMEOUT_MS = 30_000


@pytest.fixture()
def race_engine(tmp_path):
    """A file-backed SQLite engine configured like the production one."""
    db_path = tmp_path / "race.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # Without this a second writer fails immediately with "database is
        # locked" instead of waiting — which would make the race test flaky
        # for a reason that has nothing to do with the endpoint.
        cursor.execute(f"PRAGMA busy_timeout={RACE_BUSY_TIMEOUT_MS}")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def race_sessionmaker(race_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=race_engine)


@pytest.fixture()
def race_client(race_sessionmaker):
    """TestClient whose requests each get their own Session, as in production."""

    def override_get_db():
        session = race_sessionmaker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def race_auth_headers(race_client, race_sessionmaker):
    """Seed an owner into the race database and return its auth header."""
    session = race_sessionmaker()
    try:
        role = models.Role(name="owner", display_name="Owner", is_system=True)
        session.add(role)
        session.flush()
        persona = models.Persona(
            name="analyst",
            description="Test",
            data_access_level="full",
            can_modify_data=True,
            is_system=True,
        )
        session.add(persona)
        session.flush()
        session.add(models.User(
            username="raceowner",
            hashed_password=hash_password("testpass"),
            role_id=role.id,
            persona_id=persona.id,
        ))
        session.commit()
    finally:
        session.close()

    resp = race_client.post(
        "/api/auth/login", json={"username": "raceowner", "password": "testpass"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def race_account(race_sessionmaker, race_auth_headers):
    """Return the id of an account owned by the race database's owner."""
    session = race_sessionmaker()
    try:
        user = session.query(models.User).filter(
            models.User.username == "raceowner"
        ).first()
        account = models.Account(
            user_id=user.id,
            name="Race Cheque",
            account_type="checking",
            balance=1000.0,
            currency="AUD",
        )
        session.add(account)
        session.commit()
        return account.id
    finally:
        session.close()
