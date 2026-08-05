# Liorin Structured Data Schema

The structured dataset is aligned with the TraceMind product manuals and models
enterprise technical-product post-sales support.

The data is still synthetic, but the generator intentionally includes more
production-like irregularity: non-linear product prices, mixed customer email
patterns, channel and CRM provenance fields, partial support records, lifecycle
event history, and varied ticket summaries.

## Tables

- `customers`: customer identity, tenant, segment context, activity score, optional phone, company name, and source system.
- `products`: product catalog derived from `data/knowledge/manuals`.
- `orders`: order snapshot, tracking, cancellation reason, channel, sales rep, discount code, and original amount.
- `order_items`: line items connected to products, with channel/contract-adjusted unit prices.
- `order_status_events`: order lifecycle events such as created, paid, processing, shipped, delivered, and cancelled.
- `tickets`: after-sales troubleshooting and repair intake records, including channel, team assignment, attachment count, sentiment, and occasional missing order links.
- `ticket_events`: ticket lifecycle events such as created, assigned, first response, pending customer, reopened, and resolved.
- `warranty_cases`: warranty eligibility, coverage type, and coverage status records.

`customers.email` is used by the support workflow for identity verification.
Product manual files are stored under `data/knowledge/manuals`.

## Current Scale

- `customers`: 300 rows.
- `products`: 20 rows.
- `orders`: 1,500 rows.
- `order_items`: 3,355 rows.
- `order_status_events`: 7,296 rows.
- `tickets`: 420 rows.
- `ticket_events`: 1,633 rows.
- `warranty_cases`: 140 rows.

## Generation Logic

- Product profiles define category, warranty months, expected issue families,
  support issue rate, and warranty escalation rate.
- Product catalog prices use product-specific market-like anchors rather than a
  smooth numeric sequence by product ID.
- Customer identities include consumer and enterprise patterns, shared inboxes,
  mixed email domains, optional phone numbers, varied source systems, and some
  display-name formatting noise.
- Customer activity still contributes to purchase frequency, but order behavior
  also varies by segment, channel, product category, discount, and random demand.
- Order lifecycle status is based on order age relative to August 4, 2026, and
  each order also has event rows describing its lifecycle.
- Cancelled orders retain line items and original order amount, include
  `cancel_reason`, and do not have tracking numbers.
- Enterprise customers are more likely to create multi-line orders.
- Item quantity depends on product category: low-volume equipment rarely appears
  in bulk, while input devices, wearables, small appliances, and air-treatment
  products can appear in larger enterprise quantities.
- `products.currently_in_stock` describes current catalog availability, not
  historical inventory at the time of older orders.
- Most tickets are created from shipped or delivered order items, but a small
  number intentionally have no `order_id` to mimic phone/email intake without a
  reliable order number.
- Root tickets with known order links are unique per order, product, and issue
  type; unknown-order tickets may contain realistic duplicate intake noise.
- Repeat or reopened tickets point to `parent_ticket_id`.
- Ticket priority depends on issue severity and customer segment.
- Ticket summaries use mixed wording and may contain incomplete legacy-import
  style details or blank summaries.
- Warranty cases are escalated from eligible root tickets with known order links
  and point to `ticket_id`.
- A single known business incident, defined as `(order_id, product_id,
  issue_type)`, can have at most one warranty case.
- Warranty expiry is computed from order date plus product warranty months.
  `coverage_type = extended_warranty` adds 12 months before expiry is evaluated.
- `coverage_status` records whether the case is currently in warranty or
  expired; it does not replace the original warranty type.
- `active` and `under_review` warranty cases cannot be past expiry; `expired`
  cases cannot have future expiry.
