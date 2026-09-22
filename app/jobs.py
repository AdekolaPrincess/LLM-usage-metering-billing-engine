import time
from datetime import datetime, timezone
from app.database import SessionLocal
from app.models import Tenant, UsageEvent, MonthlyRollup, JobFailureLog
from app.pricing import calculate_ai_token_cost_cents, calculate_api_call_cost_cents


def calculate_tenant_rollup(db, tenant, month_str, start_of_month):

    # Calculates one tenant's usage and cost for the current month, and saves it as a MonthlyRollup row
    
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

    api_call_cost_cents = calculate_api_call_cost_cents(api_calls_used)
    ai_token_cost_cents = sum(
        calculate_ai_token_cost_cents(
            e.input_tokens, e.cached_input_tokens, e.output_tokens, e.reasoning_tokens
        )
        for e in token_events
    )
    total_cost_cents = round(api_call_cost_cents + ai_token_cost_cents)

    plan_name = tenant.current_plan.name

    rollup = MonthlyRollup(
        tenant_id=tenant.id,
        month=month_str,
        api_calls_used=api_calls_used,
        ai_tokens_used=tokens_used,
        cost_cents=total_cost_cents,
            plan_name = tenant.current_plan.name
    )
    db.add(rollup)
    db.commit()


def run_monthly_rollup_job():
    
    # The actual background job
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    tenants = db.query(Tenant).all()

    for tenant in tenants:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                calculate_tenant_rollup(db, tenant, month_str, start_of_month)
                break  # success, move to the next tenant
            except Exception as e:
                if attempt == max_attempts:
                    # All retries used up, log the failure and move on so that one tenant's failure doesn not stop the whole job.
                    db.add(JobFailureLog(
                        job_name="monthly_rollup",
                        tenant_id=tenant.id,
                        error_message=str(e),
                    ))
                    db.commit()
                else:
                    time.sleep(0.5)  # brief pause before retrying

    db.close()