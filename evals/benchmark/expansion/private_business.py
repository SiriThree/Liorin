"""Phase D1 deterministic Private Business semantic-family definitions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilySpec:
    family_id: str
    record_type: str
    template_id: str
    fields: tuple[str, ...]
    count: int
    surface_template_id: str
    query_template: str
    reasoning_type: str = "DIRECT_LOOKUP"
    requires_single_item_order: bool = False


ORDER_FAMILIES = (
    FamilySpec("ORDER_STATUS_LOOKUP", "order", "order_detail", ("status",), 5, "order-status-v1", "请帮我查一下订单 {ref} 现在是什么状态？"),
    FamilySpec("ORDER_DATE_LOOKUP", "order", "order_detail", ("order_date",), 4, "order-date-v1", "订单 {ref} 是哪天下单的？"),
    FamilySpec("ORDER_PRODUCT_LOOKUP", "order", "order_detail", ("product_id", "product_name"), 5, "order-product-v1", "订单 {ref} 购买的是什么产品？", requires_single_item_order=True),
    FamilySpec("ORDER_QUANTITY_LOOKUP", "order", "order_detail", ("quantity",), 4, "order-quantity-v1", "订单 {ref} 里的这件产品买了几件？", requires_single_item_order=True),
    FamilySpec("ORDER_UNIT_PRICE_LOOKUP", "order", "order_detail", ("price_per_unit",), 4, "order-unit-price-v1", "订单 {ref} 里这件产品的单价是多少？", requires_single_item_order=True),
    FamilySpec("ORDER_AMOUNT_LOOKUP", "order", "order_detail", ("total_amount",), 4, "order-amount-v1", "订单 {ref} 的订单总金额是多少？"),
    FamilySpec("ORDER_CHANNEL_LOOKUP", "order", "order_detail", ("channel",), 4, "order-channel-v1", "订单 {ref} 是通过什么渠道下单的？"),
    FamilySpec("ORDER_MULTI_FIELD_SUMMARY", "order", "order_detail", ("status", "order_date"), 6, "order-summary-v1", "请同时告诉我订单 {ref} 的当前状态和下单日期。", reasoning_type="MULTI_FIELD_STRUCTURED"),
)

TICKET_FAMILIES = (
    FamilySpec("TICKET_STATUS_LOOKUP", "ticket", "ticket_detail", ("status",), 4, "ticket-status-v1", "请帮我查一下工单 {ref} 现在是什么状态？"),
    FamilySpec("TICKET_PRIORITY_LOOKUP", "ticket", "ticket_detail", ("priority",), 3, "ticket-priority-v1", "工单 {ref} 当前的优先级是什么？"),
    FamilySpec("TICKET_ISSUE_TYPE_LOOKUP", "ticket", "ticket_detail", ("issue_type",), 3, "ticket-issue-v1", "工单 {ref} 记录的问题类型是什么？"),
    FamilySpec("TICKET_PRODUCT_LOOKUP", "ticket", "ticket_detail", ("product_id",), 3, "ticket-product-v1", "工单 {ref} 对应的是哪款产品？"),
    FamilySpec("TICKET_ORDER_LINK_LOOKUP", "ticket", "ticket_detail", ("order_id",), 3, "ticket-order-link-v1", "工单 {ref} 关联的是哪一笔订单？"),
    FamilySpec("TICKET_ASSIGNED_TEAM_LOOKUP", "ticket", "ticket_detail", ("assigned_team",), 3, "ticket-team-v1", "工单 {ref} 目前分配给哪个处理团队？"),
    FamilySpec("TICKET_SUMMARY_LOOKUP", "ticket", "ticket_detail", ("summary",), 3, "ticket-summary-v1", "工单 {ref} 里记录的问题摘要是什么？"),
    FamilySpec("TICKET_CREATED_AT_LOOKUP", "ticket", "ticket_detail", ("created_at",), 2, "ticket-created-v1", "工单 {ref} 是什么时候创建的？"),
    FamilySpec("TICKET_MULTI_FIELD_SUMMARY", "ticket", "ticket_detail", ("status", "priority"), 2, "ticket-summary-multi-v1", "请同时告诉我工单 {ref} 的状态和优先级。", reasoning_type="MULTI_FIELD_STRUCTURED"),
)

WARRANTY_FAMILIES = (
    FamilySpec("WARRANTY_STATUS_LOOKUP", "warranty", "warranty_cases", ("status",), 3, "warranty-status-v1", "请帮我查一下质保案例 {ref} 当前是什么状态？"),
    FamilySpec("WARRANTY_COVERAGE_STATUS_LOOKUP", "warranty", "warranty_cases", ("coverage_status",), 4, "warranty-coverage-status-v1", "质保案例 {ref} 当前是否仍在保修范围内？"),
    FamilySpec("WARRANTY_COVERAGE_TYPE_LOOKUP", "warranty", "warranty_cases", ("coverage_type",), 3, "warranty-coverage-type-v1", "质保案例 {ref} 属于哪种保修类型？"),
    FamilySpec("WARRANTY_EXPIRY_LOOKUP", "warranty", "warranty_cases", ("expires_at",), 3, "warranty-expiry-v1", "质保案例 {ref} 的到期日期是什么时候？"),
    FamilySpec("WARRANTY_PRODUCT_LOOKUP", "warranty", "warranty_cases", ("product_id",), 3, "warranty-product-v1", "质保案例 {ref} 对应的是哪款产品？"),
    FamilySpec("WARRANTY_ORDER_LINK_LOOKUP", "warranty", "warranty_cases", ("order_id",), 2, "warranty-order-link-v1", "质保案例 {ref} 关联的是哪一笔订单？"),
    FamilySpec("WARRANTY_TICKET_LINK_LOOKUP", "warranty", "warranty_cases", ("ticket_id",), 2, "warranty-ticket-link-v1", "质保案例 {ref} 关联的是哪个工单？"),
    FamilySpec("WARRANTY_MULTI_FIELD_SUMMARY", "warranty", "warranty_cases", ("coverage_status", "expires_at"), 2, "warranty-summary-v1", "请同时告诉我质保案例 {ref} 的保修状态和到期日期。", reasoning_type="MULTI_FIELD_STRUCTURED"),
)

ALL_FAMILIES = ORDER_FAMILIES + TICKET_FAMILIES + WARRANTY_FAMILIES
