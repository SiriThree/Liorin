# Liorin Data Utilities

Utilities for rebuilding local development artifacts from the committed Liorin
dataset.

## Data Sources

- `data/knowledge/manuals`: TraceMind product manuals converted to Markdown.
- `data/knowledge/policies`: Liorin after-sales policy documents.
- `data/structured/*.json`: sample enterprise support data aligned with the
  manuals.
- `evals/tracemind`: copied TraceMind benchmark and public question datasets.

## Commands

```bash
uv run python data/data_generation/generate_structured_data.py
uv run python data/data_generation/create_database.py
uv run python data/data_generation/validate_database.py
uv run python data/data_generation/build_vectorstore.py
```

## Outputs

| Script | Output | Purpose |
|---|---|---|
| `generate_structured_data.py` | `data/structured/*.json` | Larger, production-noisy synthetic customer/order/support dataset aligned with TraceMind products |
| `create_database.py` | `data/structured/liorin.db` | SQLite database for Order Agent queries |
| `validate_database.py` | validation report | Integrity checks for the structured dataset |
| `build_vectorstore.py` | configured Milvus collection | RAG index for manuals, policies, and FAQ |

The default generated scale is 300 customers, 1,500 orders, 3,000+ order items,
7,000+ order lifecycle events, roughly 420 tickets, 1,600+ ticket lifecycle
events, and roughly 140 warranty cases.

## Business Causality

The generated dataset is synthetic, but not purely random or overly clean:

- Product categories, warranty windows, issue families, and issue rates are
  derived from TraceMind product names.
- Product prices use product-specific market-like anchors instead of a smooth
  sequence by product ID.
- Customer order activity is stored as `activity_score` and follows a long-tail
  distribution, while channel, segment, discount, product category, and random
  demand also affect purchases.
- Customer records include mixed email domains, shared enterprise inboxes,
  optional phone numbers, source-system provenance, and display-name noise.
- Order status is derived from order age relative to `CURRENT_DATE`.
- `order_status_events` records lifecycle history for each order.
- Cancelled orders preserve their intended line items and original total, record
  `cancel_reason`, and do not receive a tracking number.
- Enterprise customers have higher probability of multi-line orders.
- Quantity is product-category aware: low-volume products such as marine
  vehicles, major appliances, HVAC, pumps, and generators rarely appear in bulk,
  while smaller operational items can be purchased in larger enterprise batches.
- `currently_in_stock` means current catalog availability. It is not interpreted
  as historical stock at the time an older order was placed.
- Most support tickets are generated from real shipped or delivered order items
  using product-specific issue probabilities, product age, order status, and
  quantity. A small number intentionally have no order link to mimic phone/email
  intake without a reliable order number.
- If ticket volume falls below the minimum range, supplements prefer unused
  root issue keys; unavoidable repeats are represented as follow-up tickets.
- Repeat or reopened tickets reference `parent_ticket_id`.
- Ticket priority is influenced by issue type and customer segment.
- Ticket summaries use varied phrasing, including bilingual customer language,
  incomplete legacy-import details, and a small number of blank summaries.
- `ticket_events` records lifecycle history for support tickets.
- Warranty cases are escalated from eligible root support tickets and reference
  `ticket_id`; follow-up tickets and unknown-order tickets do not create
  separate warranty cases.
- A single known business incident, defined as `(order_id, product_id,
  issue_type)`, can create at most one warranty case.
- Warranty expiry dates are computed from order date and `coverage_type`.
  `extended_warranty` adds 12 months to the product warranty window.
- `coverage_status` records whether the case is in warranty or expired; it is
  validated independently from workflow `status`.

The default embedding provider is HuggingFace. Set `EMBEDDING_PROVIDER=openai`
to build the Milvus collection with OpenAI embeddings.

Milvus is configured with `MILVUS_URI`, `MILVUS_TOKEN`, and
`MILVUS_COLLECTION`. Start a Milvus server before rebuilding:

```bash
uv run python data/data_generation/build_vectorstore.py
```
