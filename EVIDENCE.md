# Evidence

This file contains proof for each requirement in the capstone brief, taken from real test runs against the running service.

## Metering: duplicate requests do not create duplicate usage events

Request sent with idempotency_key "test-key-1":

First call:
​```
status   usage_event_id usage_type quantity
------   -------------- ---------- --------
recorded              1 api_call          1
​```

Same request sent again, same idempotency_key:
​```
status            usage_event_id usage_type quantity
------            -------------- ---------- --------
duplicate_ignored              1 api_call          1
​```

The second call returns the same usage_event_id (1) and does not create a new event, confirming the same idempotency key can never be recorded twice.

## Quota enforcement: requests over the limit are rejected with 429

Free plan token quota is 100,000 tokens/month. A request was sent for 200,000 tokens in a single call:

​```
Invoke-RestMethod -Uri "http://127.0.0.1:8000/generate" -Method Post -Headers @{"X-API-Key"="..."} -Body (@{usage_type="ai_tokens"; quantity=200000; idempotency_key="test-quota-1"} | ConvertTo-Json) -ContentType "application/json"
​```

Server response:
​```
INFO:     127.0.0.1:61032 - "POST /generate HTTP/1.1" 429 Too Many Requests
​```

The request was rejected with a 429 status code because it would have pushed the tenant's monthly token usage above their plan's quota, confirming quota enforcement happens before the usage event is recorded.

## Cost calculation: AI token pricing rules produce correct totals

Pricing constants (pinned in app/pricing.py):
- Input tokens: 0.3 cents per 1,000
- Cached input tokens: 0.075 cents per 1,000 (cheaper than fresh input)
- Output tokens: 1.5 cents per 1,000
- Reasoning tokens: billed at the output rate (1.5 cents per 1,000), not a separate category

A usage event was recorded with the following breakdown:
- input_tokens: 1000
- cached_input_tokens: 2000
- output_tokens: 500
- reasoning_tokens: 300

Hand calculation:
- Input: 1000 / 1000 x 0.3 = 0.3 cents
- Cached input: 2000 / 1000 x 0.075 = 0.15 cents
- Output: 500 / 1000 x 1.5 = 0.75 cents
- Reasoning (at output rate): 300 / 1000 x 1.5 = 0.45 cents
- Total: 0.3 + 0.15 + 0.75 + 0.45 = 1.65 cents, rounded to 2 cents

Server response from GET /usage after recording this event:
​```
plan cost_cents
---- ----------
Free          2
​```

The server's calculated cost (2 cents) matches the hand calculation exactly, confirming cached input tokens are billed cheaper than fresh input, and reasoning tokens are correctly billed at the output rate rather than being added as a separate, differently priced category.

## Stripe integration: webhook signature verification

A test event was triggered using the Stripe CLI (`stripe trigger checkout.session.completed`), forwarded to the local webhook endpoint via `stripe listen`. All resulting events were correctly verified and accepted:

​```
2026-09-10 16:06:00   --> product.created [evt_1UE9YvRM8GoWpVlfra2eJBCb]
2026-09-10 16:06:00  <--  [200] POST http://localhost:8000/webhooks/stripe [evt_1UE9YvRM8GoWpVlfra2eJBCb]
2026-09-10 16:06:11   --> checkout.session.completed [evt_1UE9Z6RM8GoWpVlfS6PWdYMJ]
2026-09-10 16:06:11  <--  [200] POST http://localhost:8000/webhooks/stripe [evt_1UE9Z6RM8GoWpVlfS6PWdYMJ]
​```

Every event returned a 200 status, confirming the webhook signature was successfully verified for genuine Stripe-originated events using the shared webhook secret.

## Stripe integration: checkout flips a tenant from Free to Pro

A new tenant was created (defaulting to the Free plan), a Checkout session was created via POST /checkout, and the checkout was completed in the browser using Stripe's test card (4242 4242 4242 4242). The webhook for checkout.session.completed was received and processed.

GET /usage was then called for the same tenant:

​```
plan api_calls              ai_tokens                cost_cents
---- ---------              ---------                ----------
Pro  @{used=0; limit=50000} @{used=0; limit=5000000}          0
​```

The tenant's plan changed from Free to Pro, and the usage limits shown (50,000 API calls, 5,000,000 AI tokens) match the Pro plan's quotas, confirming the webhook correctly updated the tenant's plan and that GET /usage reflects the new limits.

## Stripe integration: forged webhook signatures are rejected

A request was sent directly to /webhooks/stripe with a fabricated stripe-signature header (not calculated by Stripe):

​```
400
{"detail":"Invalid webhook signature"}
​```

The request was rejected with a 400 status code, confirming forged or invalid signatures are never trusted or processed.

## Stripe integration: duplicate event delivery is processed only once

A genuine, correctly-signed event (evt_1UEotPRM8GoWpVlfQmzW7EKO) was sent to the webhook endpoint twice using `stripe events resend`. Both deliveries returned 200 OK.

Querying the database directly for this event ID afterward:

​```
python -c "from app.database import SessionLocal; from app.models import ProcessedWebhookEvent; db = SessionLocal(); rows = db.query(ProcessedWebhookEvent).filter(ProcessedWebhookEvent.stripe_event_id == 'evt_1UEotPRM8GoWpVlfQmzW7EKO').all(); print(f'Found {len(rows)} row(s) for this event ID')"

Found 1 row(s) for this event ID
​```

Only one row exists for this event ID despite two deliveries, confirming the second delivery was correctly recognized as a duplicate and not reprocessed.

## Stripe integration: subscription cancellation reverts tenant to Free plan

A tenant's Pro subscription was canceled directly in the Stripe sandbox, triggering a genuine `customer.subscription.deleted` webhook event.

Database state before cancellation:
​```
tenant plan_id: 2   (Pro)
subscription status: active
​```

After the webhook was received and processed:
​```
tenant plan_id: 1   (Free)
subscription status: canceled
subscription ended_at: 2026-09-12 19:22:15.400783
​```

The tenant's plan was correctly reverted to Free, and the subscription record was marked canceled with a real timestamp, confirming the webhook handler correctly processes subscription cancellations, not just new subscriptions.

## Background job: monthly rollup with retries and failure logging

POST /admin/run-rollup-job starts a monthly usage rollup job that runs after the response is returned to the caller (using FastAPI's BackgroundTasks), rather than blocking the request.

Happy path: a tenant with 5 recorded API calls had the job run against them. Checking the monthly_rollups table afterward:
​```
tenant_id  month     api_calls_used  ai_tokens_used  cost_cents
1          2026-09   5               0               0
​```

A real rollup row was created with the correct usage totals, confirming the job actually performs the calculation work, not just returning a fake "started" response.

Failure and retry path: a tenant's plan reference was deliberately corrupted (set to a non-existent plan id), causing the rollup calculation to genuinely fail when looking up the tenant's plan. The job was run again:

​```
job_name        tenant_id  error_message                              failed_at
monthly_rollup   1          'NoneType' object has no attribute 'name'  2026-09-22 13:54:27.241669
​```

The job retried the failing tenant up to 3 times, then logged the failure to job_failure_log instead of crashing, confirming the job handles per-tenant failures gracefully and does not lose the error silently.