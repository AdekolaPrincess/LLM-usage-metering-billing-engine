from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
import secrets
from app.database import SessionLocal
from app.models import Tenant, Plan, UsageEvent

app = FastAPI()

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
    usage_type: str   # api_call or ai_tokens
    quantity: int
    idempotency_key: str


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
    # check if we've already processed this exact idempotency key, return the same result if so instead of creating a new event
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

    # figure out how much of this usage_type the tenant has used so far this calendar month.
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

    # check this against the tenant's plan quota.
    plan = tenant.current_plan
    if request.usage_type == "api_call":
        quota = plan.api_call_quota
    elif request.usage_type == "ai_tokens":
        quota = plan.ai_token_quota
    else:
        raise HTTPException(status_code=400, detail="usage_type must be 'api_call' or 'ai_tokens'")

    if used_so_far + request.quantity > quota:
        raise HTTPException(
            status_code=429,
            detail=f"Quota exceeded: {used_so_far} used, {quota} allowed this month for {request.usage_type}",
        )

    # within quota, safe to record this usage event.
    event = UsageEvent(
        tenant_id=tenant.id,
        usage_type=request.usage_type,
        quantity=request.quantity,
        idempotency_key=request.idempotency_key,
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