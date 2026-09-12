from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key= True)
    name = Column(String, unique= True, nullable =  False)
    api_call_quota = Column(Integer, nullable= False)
    ai_token_quota = Column(Integer, nullable = False)
    price_cents = Column(Integer, nullable = False)

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    api_key = Column(String, unique=True, nullable=False)
    current_plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    stripe_customer_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    current_plan = relationship("Plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    stripe_subscription_id = Column(String, unique=True, nullable=True)
    status = Column(String, nullable=False, default="active")
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant")
    plan = relationship("Plan")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    usage_type = Column(String, nullable=False)                  # api_call or ai_tokens
    quantity = Column(Integer, nullable=False)                   # total count, used for quota checks
    idempotency_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Only used when usage_type is ai_tokens, these break the total down into the categories that price differently and stay 0 for api_call events.
    input_tokens = Column(Integer, nullable=False, default=0)
    cached_input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    reasoning_tokens = Column(Integer, nullable=False, default=0)

    tenant = relationship("Tenant")

class ProcessedWebhookEvent(Base):
    __tablename__ = "processed_webhook_events"

    id = Column(Integer, primary_key=True)
    stripe_event_id = Column(String, unique=True, nullable=False)
    processed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))