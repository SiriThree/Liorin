# Liorin Structured Data Schema

The structured dataset is aligned with the TraceMind product manuals and models enterprise technical-product after-sales support.

## Tables

- `customers`: customer identity, tenant, and segment context.
- `products`: product catalog derived from `data/knowledge/manuals`.
- `orders`: order lifecycle and tracking information.
- `order_items`: line items connected to products.
- `tickets`: after-sales troubleshooting and repair intake records.
- `warranty_cases`: warranty eligibility and coverage records.

`customers.email` is used by the support workflow for identity verification. Product manual files are stored under `data/knowledge/manuals`.
