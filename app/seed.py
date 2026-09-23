from app.database import Base, engine, SessionLocal
from app.models import Plan

db = SessionLocal()

existing = db.query(Plan).count()
if existing == 0:        # Only add plans if they do not exist to avoid duplicates
    free_plan = Plan(
        name="Free",
        api_call_quota=1000,
        ai_token_quota=100000,
        price_cents=0,
    )
    pro_plan = Plan(
        name="Pro",
        api_call_quota=50000,
        ai_token_quota=5000000,
        price_cents=2900,
    )
    db.add(free_plan)
    db.add(pro_plan)
    db.commit()
    print("Created Free and Pro plans.")
else:
    print(f"Plans already exist ({existing} found), skipping seed.")

db.close()