"""Authentication metadata; raw passwords, session tokens and tickets never persist."""
from sqlalchemy import Column, Integer, String, Float, Table, DateTime, CheckConstraint, LargeBinary
from .db import Base


# Register legacy raw-SQL tables too: revocation triggers must see these tables
# even on a fresh database, before db.run_migrations() executes. Schemas match
# those migrations; existing databases are not altered by create_all().
telegram_bindings = Table('driver_telegram_bindings', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('car_code', String, nullable=False),
    Column('driver_name', String, server_default=''),
    Column('telegram_chat_id', String, nullable=False),
    Column('telegram_username', String, server_default=''),
    Column('telegram_first_name', String, server_default=''),
    Column('linked_at', DateTime),
    Column('last_alert_level', String, server_default=''),
    Column('last_alert_at', DateTime))
telegram_links = Table('driver_telegram_links', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('car_code', String, nullable=False),
    Column('driver_name', String, server_default=''),
    Column('link_token', String, unique=True, nullable=False),
    Column('created_at', DateTime), Column('expires_at', DateTime),
    Column('used_at', DateTime))


# Created during ordered schema initialization, never by a document GET.
vehicle_documents = Table('vehicle_documents', Base.metadata,
    Column('car_code', String(32), primary_key=True),
    Column('license_filename', String(255), nullable=False),
    Column('license_mime_type', String(100), nullable=False, server_default='application/pdf'),
    Column('license_data', LargeBinary, nullable=False),
    Column('uploaded_at', DateTime, nullable=False))


class Owner(Base):
    __tablename__ = 'auth_owners'
    __table_args__ = (CheckConstraint('id = 1', name='auth_single_owner'),)
    id = Column(Integer, primary_key=True)
    username = Column(String(128), nullable=False, unique=True)
    password_hash = Column(String(512), nullable=False)


class HermesCredential(Base):
    __tablename__ = 'auth_hermes_credentials'
    id = Column(Integer, primary_key=True)
    label = Column(String(128), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    scope = Column(String(32), nullable=False, default='finance:read')
    created_at = Column(Float, nullable=False)
    expires_at = Column(Float)
    revoked_at = Column(Float)


class LoginAttempt(Base):
    __tablename__ = 'auth_login_attempts'
    key = Column(String(64), primary_key=True)
    window_start = Column(Float, nullable=False, index=True)
    attempts = Column(Integer, nullable=False)


class DriverEpoch(Base):
    __tablename__ = 'auth_driver_epochs'
    car_code = Column(String, primary_key=True)
    epoch = Column(Integer, nullable=False, default=0)


class DriverTicket(Base):
    __tablename__ = 'auth_driver_tickets'
    token_hash = Column(String(64), primary_key=True)
    car_code = Column(String, nullable=False)
    driver_name = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    epoch = Column(Integer, nullable=False)
    expires_at = Column(Float, nullable=False)
    consumed_at = Column(Float)
    revoked_at = Column(Float)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash = Column(String(64), primary_key=True)
    kind = Column(String(16), nullable=False)
    chat_id = Column(String)
    owner_id = Column(Integer)
    car_code = Column(String)
    driver_name = Column(String)
    epoch = Column(Integer)
    csrf_token = Column(String(128), nullable=False)
    expires_at = Column(Float, nullable=False)
    revoked_at = Column(Float)
