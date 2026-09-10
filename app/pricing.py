PRICE_PER_1K_INPUT_TOKENS_CENTS = 0.3          # fresh input tokens
PRICE_PER_1K_CACHED_INPUT_TOKENS_CENTS = 0.075  # cached input, 4x cheaper than fresh
PRICE_PER_1K_OUTPUT_TOKENS_CENTS = 1.5          # output tokens (also covers reasoning tokens)

# Flat price for a single API call (the "api_call" usage type, unrelated to tokens).
PRICE_PER_API_CALL_CENTS = 0.1

# Stripe price ID for the Pro plan subscription, created once via the Stripe CLI.
STRIPE_PRO_PRICE_ID = "price_1UE9GYRM8GoWpVlfDGe9hVm4"


def calculate_ai_token_cost_cents(input_tokens, cached_input_tokens, output_tokens, reasoning_tokens):
    """
    Calculates the cost, in cents, for a set of AI token usage.
    Reasoning tokens are billed at the OUTPUT rate, not their own rate,
    per the brief's pricing rule.
    """
    input_cost = (input_tokens / 1000) * PRICE_PER_1K_INPUT_TOKENS_CENTS
    cached_cost = (cached_input_tokens / 1000) * PRICE_PER_1K_CACHED_INPUT_TOKENS_CENTS
    output_cost = (output_tokens / 1000) * PRICE_PER_1K_OUTPUT_TOKENS_CENTS
    reasoning_cost = (reasoning_tokens / 1000) * PRICE_PER_1K_OUTPUT_TOKENS_CENTS  # billed as output

    return input_cost + cached_cost + output_cost + reasoning_cost


def calculate_api_call_cost_cents(quantity):
    """Calculates the cost, in cents, for a number of plain API calls."""
    return quantity * PRICE_PER_API_CALL_CENTS