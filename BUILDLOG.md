# Build Log

This project was built with AI assistance (Claude), acting as a step-by-step tutor. This log records where AI helped, where it produced mistakes, and what was changed as a result.

## Where AI helped

- Explaining backend and billing concepts in plain language before writing any code (idempotency, quotas, ORMs, webhooks, signature verification).
- Structuring the project into layers (HTTP, logic, data) and writing the initial FastAPI, SQLAlchemy, and Stripe integration code.
- Designing the AI token pricing formula (cached input cheaper, reasoning billed as output) and verifying it against a hand calculation.
- Walking through debugging real errors (an empty database file from an interrupted script, and indentation bugs) by reading actual tracebacks rather than guessing at fixes.

## Where AI was wrong, and what was changed

- The AI initially wrote the architecture diagram in DESIGN.md without wrapping it in markdown code fences, which caused it to render as a jumbled, unreadable mess instead of a formatted diagram. This was caught after viewing the rendered file and comparing it to what was intended. Fixed by adding the missing code fences.
- The AI wrote a webhook handler where the elif branch for handling customer.subscription.deleted events was nested one level too deep, inside the if tenant: block from the checkout-completion branch, instead of being a sibling of the outer event-type check. This meant subscription cancellation webhooks were silently never processed, despite the endpoint returning 200 OK. This was only caught by testing an actual subscription cancellation and checking the real database state afterward, not by trusting the successful HTTP response. The AI's first attempted fix still contained a version of the same structural mistake, it took a second, closer comparison of the actual pasted code to correctly identify and fix the real issue.

## What was written and verified independently

- Every endpoint was tested manually using PowerShell's Invoke-RestMethod against the running local server.
- The idempotency, quota enforcement, and cost calculation logic were verified against hand calculations and real request/response transcripts, documented in EVIDENCE.md.
- Every git commit was reviewed (via git status) before staging, to confirm only intended files were included.