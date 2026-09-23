# Design Doc: LLM Usage Metering & Billing Engine

## Problem

Every SaaS product needs to answer three questions for each customer:
how much have they used, what should they pay, and have they hit their plan limit.
This service answers all three: it meters usage, enforces quotas, calculates cost
(including AI token pricing rules), and syncs subscription state with Stripe in test mode.

## Data model

**Tenant**
- id
- name
- current_plan_id (points to Plan)
- stripe_customer_id
- created_at

**Plan**
- id
- name (Free / Pro)
- api_call_quota (Free: 1,000/month, Pro: 50,000/month)
- ai_token_quota (Free: 100,000/month, Pro: 5,000,000/month)
- price_cents (Free: 0, Pro: 2900)

**Subscription**
- id
- tenant_id (points to Tenant)
- plan_id (points to Plan)
- stripe_subscription_id
- status (active / canceled / past_due)
- started_at
- ended_at

**Usage event**
- id
- tenant_id (points to Tenant)
- usage_type (api_call / ai_tokens)
- quantity
- idempotency_key
- created_at

## Relationships

- One Plan can be used by many Tenants.
- One Tenant has one Subscription.
- One Subscription points to one Plan.
- One Tenant owns many Usage events.

## API surface

- POST /tenants - create a new tenant, returns an API key
- POST /generate - the dummy billable action (requires API key + Idempotency-Key header)
- GET /usage - returns used, limit, and cost for the calling tenant
- POST /checkout - creates a Stripe Checkout session for upgrading to Pro
- POST /webhooks/stripe - receives and verifies Stripe webhook events

## Layer sketch

HTTP layer (routes, input validation, status codes)
  -> Logic layer (quota rules, cost calculation, idempotency decisions)
    -> Data layer (the only layer that talks to the database)

Example flow for POST /generate:

Request arrives -> HTTP layer validates input
  -> Logic layer asks Data layer: has this idempotency key been used?
  -> Logic layer asks Data layer: what is this tenant's usage so far?
  -> Logic layer decides: allow, or return 429/402
  -> Logic layer asks Data layer: save the new usage event
-> HTTP layer returns the JSON response + status code

## Architecture diagram (ASCII sketch)

```
                    +------------------+
                    |     Client       |
                    +------------------+
                            |
                            v
                 +----------------------+
                 |     HTTP layer       |
                 | (routes, validation) |
                 +----------------------+
                            |
                            v
                 +----------------------+
                 |     Logic layer      |
                 | (quotas, cost rules, |
                 |  idempotency checks) |
                 +----------------------+
                            |
                            v
                 +----------------------+
                 |     Data layer       |
                 | (Postgres/SQLite)    |
                 +----------------------+
                            |
        +-------------------+-------------------+
        |                   |                    |
        v                   v                    v
   +---------+         +---------+         +--------------+
   | Tenant  |         |  Plan   |         | Usage event  |
   +---------+         +---------+         +--------------+
        |
        v
  +--------------+
  | Subscription |
  +--------------+


   Stripe (test mode)
        |
        | signed webhook events
        v
+---------------------------+
|   POST /webhooks/stripe   |
| verify signature          |
| deduplicate event         |
| update Subscription/Plan  |
+---------------------------+
```

## Idempotency strategy

Every call to POST /generate must include an Idempotency-Key header, generated
by the caller. Before creating a new usage event, the data layer checks whether
a usage event already exists for that tenant with that exact key. If it exists,
the original result is returned and no new event is created. If it does not exist,
a new usage event is created and the key is stored with it.

## Non-goal

This system does not support overage billing, mid-cycle plan proration, or
invoicing. When a tenant exceeds their quota, the request is rejected with a
429 or 402 response. They are not charged extra, and no partial credit is
calculated for a mid-month upgrade. These are documented as stretch goals only.

## Quota boundary rule

A tenant may use up to and including their exact monthly quota. A request is only rejected if it would push their usage strictly above the quota. For example, with a 100,000 token quota, a request that brings total usage to exactly 100,000 succeeds; the next request, even for a single additional token, is rejected with a 429.