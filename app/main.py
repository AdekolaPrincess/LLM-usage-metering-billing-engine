from fastapi import FastAPI, Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
import secrets
import os
import stripe
from dotenv import load_dotenv
from app.database import SessionLocal
from app.models import Tenant, Plan, UsageEvent, ProcessedWebhookEvent, Subscription
from typing import Optional
from app.pricing import calculate_ai_token_cost_cents, calculate_api_call_cost_cents, STRIPE_PRO_PRICE_ID

app = FastAPI()

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_tenant(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.api_key == x_api_key).first()
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tenant

class CreateTenantRequest(BaseModel):
    name: str

class GenerateRequest(BaseModel):
    usage_type: str                      # "api_call" or "ai_tokens"
    idempotency_key: str

    # Used only when usage_type == "api_call"
    quantity: Optional[int] = None

    # Used only when usage_type == "ai_tokens"
    input_tokens: Optional[int] = 0
    cached_input_tokens: Optional[int] = 0
    output_tokens: Optional[int] = 0
    reasoning_tokens: Optional[int] = 0


@app.post("/tenants")
def create_tenant(request: CreateTenantRequest, db: Session = Depends(get_db)):
    free_plan = db.query(Plan).filter(Plan.name == "Free").first() # New tenants starts on the free plan by default
    if not free_plan:
        raise HTTPException(status_code= 500, detail = "Free plan not found, did you run the seed script?")

    api_key = secrets.token_hex(16) # Generates a random, unique API key for this tenant

    tenant = Tenant(
        name = request.name,
        api_key = api_key,
        current_plan_id = free_plan.id
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "api_key": tenant.api_key,
        "plan": free_plan.name,
    }



@app.post("/generate")
def generate(
    request: GenerateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    # idempotency check, unchanged
    existing_event = (
        db.query(UsageEvent)
        .filter(
            UsageEvent.tenant_id == tenant.id,
            UsageEvent.idempotency_key == request.idempotency_key,
        )
        .first()
    )
    if existing_event:
        return {
            "status": "duplicate_ignored",
            "usage_event_id": existing_event.id,
            "usage_type": existing_event.usage_type,
            "quantity": existing_event.quantity,
        }

    # figure out the total quantity for this request, depending on type
    if request.usage_type == "api_call":
        if request.quantity is None:
            raise HTTPException(status_code=400, detail="quantity is required for api_call")
        total_quantity = request.quantity
    elif request.usage_type == "ai_tokens":
        total_quantity = (
            (request.input_tokens or 0)
            + (request.cached_input_tokens or 0)
            + (request.output_tokens or 0)
            + (request.reasoning_tokens or 0)
        )
        if total_quantity == 0:
            raise HTTPException(status_code=400, detail="at least one token field must be greater than 0")
    else:
        raise HTTPException(status_code=400, detail="usage_type must be 'api_call' or 'ai_tokens'")

    # check usage so far this month against the plan quota.
    start_of_month = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    events_this_month = (
        db.query(UsageEvent)
        .filter(
            UsageEvent.tenant_id == tenant.id,
            UsageEvent.usage_type == request.usage_type,
            UsageEvent.created_at >= start_of_month,
        )
        .all()
    )
    used_so_far = sum(e.quantity for e in events_this_month)

    plan = tenant.current_plan
    quota = plan.api_call_quota if request.usage_type == "api_call" else plan.ai_token_quota

    if used_so_far + total_quantity > quota:
        raise HTTPException(
            status_code=429,
            detail=f"Quota exceeded: {used_so_far} used, {quota} allowed this month for {request.usage_type}",
        )

    # within quota, record the event, including the token breakdown if applicable
    event = UsageEvent(
        tenant_id=tenant.id,
        usage_type=request.usage_type,
        quantity=total_quantity,
        idempotency_key=request.idempotency_key,
        input_tokens=request.input_tokens or 0,
        cached_input_tokens=request.cached_input_tokens or 0,
        output_tokens=request.output_tokens or 0,
        reasoning_tokens=request.reasoning_tokens or 0,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "status": "recorded",
        "usage_event_id": event.id,
        "usage_type": event.usage_type,
        "quantity": event.quantity,
    }

@app.get("/usage")
def get_usage(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    start_of_month = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    api_call_events = (
        db.query(UsageEvent)
        .filter(
            UsageEvent.tenant_id == tenant.id,
            UsageEvent.usage_type == "api_call",
            UsageEvent.created_at >= start_of_month,
        )
        .all()
    )
    token_events = (
        db.query(UsageEvent)
        .filter(
            UsageEvent.tenant_id == tenant.id,
            UsageEvent.usage_type == "ai_tokens",
            UsageEvent.created_at >= start_of_month,
        )
        .all()
    )

    api_calls_used = sum(e.quantity for e in api_call_events)
    tokens_used = sum(e.quantity for e in token_events)

    plan = tenant.current_plan

    # Cost for API calls: simple flat rate per call.
    api_call_cost_cents = calculate_api_call_cost_cents(api_calls_used)

    # Cost for AI tokens: sum each event's breakdown through the pricing rules
    ai_token_cost_cents = sum(
        calculate_ai_token_cost_cents(
            e.input_tokens, e.cached_input_tokens, e.output_tokens, e.reasoning_tokens
        )
        for e in token_events
    )

    total_cost_cents = api_call_cost_cents + ai_token_cost_cents

    return {
        "plan": plan.name,
        "api_calls": {
            "used": api_calls_used,
            "limit": plan.api_call_quota,
        },
        "ai_tokens": {
            "used": tokens_used,
            "limit": plan.ai_token_quota,
        },
        "cost_cents": round(total_cost_cents),
    }

@app.post("/checkout")
def create_checkout_session(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    # If this tenant doesn't have a Stripe customer yet, create one now, and save the ID so future Stripe interactions know who this is
    if not tenant.stripe_customer_id:
        customer = stripe.Customer.create(name=tenant.name)
        tenant.stripe_customer_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=tenant.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": STRIPE_PRO_PRICE_ID, "quantity": 1}],
        success_url="http://localhost:8000/checkout-success",
        cancel_url="http://localhost:8000/checkout-cancel",
    )

    return {"checkout_url": session.url}

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Deduplication: if we've already processed this exact event ID, do nothing and just acknowledge it
    already_processed = (
        db.query(ProcessedWebhookEvent)
        .filter(ProcessedWebhookEvent.stripe_event_id == event["id"])
        .first()
    )
    if already_processed:
        return {"status": "duplicate_ignored", "type": event["type"]}

    # Handle the specific event types we care about
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        stripe_customer_id = session["customer"]
        stripe_subscription_id = session["subscription"]

        tenant = (
            db.query(Tenant)
            .filter(Tenant.stripe_customer_id == stripe_customer_id)
            .first()
        )
        if tenant:
            pro_plan = db.query(Plan).filter(Plan.name == "Pro").first()
            tenant.current_plan_id = pro_plan.id

            subscription = Subscription(
                tenant_id=tenant.id,
                plan_id=pro_plan.id,
                stripe_subscription_id=stripe_subscription_id,
                status="active",
            )
            db.add(subscription)

    # Record that we've now processed this event, so a redelivery is
    # recognized and skipped next time.
    db.add(ProcessedWebhookEvent(stripe_event_id=event["id"]))
    db.commit()

    return {"status": "processed", "type": event["type"]}