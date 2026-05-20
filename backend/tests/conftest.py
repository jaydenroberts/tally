"""
Test fixtures for Tally backend.
Uses an in-memory SQLite database — isolated per test session.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app import models
from app.auth import hash_password

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
