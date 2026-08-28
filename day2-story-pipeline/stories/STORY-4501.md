As a platform engineer I want the orders lookup endpoint rate-limited per client so that one integration cannot exhaust the connection pool.

## Acceptance criteria

- More than 100 requests per minute from one client receives HTTP 429.
- A 429 response includes a Retry-After header.
- Existing clients under the limit see no change in p95 latency.

## Dependencies

- orders-api.

## Rollback

Limiter behind the rateLimitOrders flag, default off.
