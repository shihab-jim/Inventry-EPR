"""Audited ERP business services. All mutable stock changes happen here."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Product, PurchaseOrder, PurchaseRequisition, StockMovement


@transaction.atomic
def record_stock_movement(*, product_id, movement_type, quantity, user=None, note=""):
    if movement_type not in StockMovement.MovementType.values:
        raise ValidationError("Unknown movement type.")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValidationError("Quantity must be a positive whole number.")

    product = Product.objects.select_for_update().get(pk=product_id)
    if not product.is_active:
        raise ValidationError("Inactive products cannot have stock movements.")
    if movement_type == StockMovement.MovementType.OUT:
        if quantity > product.current_stock:
            raise ValidationError("Not enough stock to complete this stock-out.")
        product.current_stock -= quantity
    else:
        product.current_stock += quantity

    product.save(update_fields=["current_stock", "updated_at"])
    movement = StockMovement.objects.create(
        product=product, movement_type=movement_type, quantity=quantity,
        note=note, created_by=user,
    )
    create_requisition_if_needed(product, user=user)
    return movement


def create_requisition_if_needed(product, *, user=None):
    if not product.needs_reorder:
        return None
    if PurchaseRequisition.objects.filter(
        product=product,
        status__in=[
            PurchaseRequisition.Status.DRAFT,
            PurchaseRequisition.Status.APPROVED,
            PurchaseRequisition.Status.ORDERED,
        ],
    ).exists():
        return None
    quantity = max(product.target_stock - product.current_stock, 0)
    if quantity <= 0:
        return None
    return PurchaseRequisition.objects.create(
        product=product, quantity=quantity, created_by=user,
        reason=(f"Auto-generated: stock {product.current_stock} is at/below "
                f"reorder level {product.reorder_level}"),
    )


@transaction.atomic
def transition_requisition(*, requisition_id, action):
    requisition = PurchaseRequisition.objects.select_for_update().get(pk=requisition_id)
    if requisition.status != PurchaseRequisition.Status.DRAFT:
        raise ValidationError("Only draft requisitions can be approved or rejected.")
    if action == "approve":
        requisition.status = PurchaseRequisition.Status.APPROVED
    elif action == "reject":
        requisition.status = PurchaseRequisition.Status.REJECTED
    else:
        raise ValidationError("Invalid approval action.")
    requisition.save(update_fields=["status"])
    return requisition


@transaction.atomic
def create_purchase_order(*, requisition_id, user=None):
    requisition = (
        PurchaseRequisition.objects.select_for_update()
        .select_related("product__supplier").get(pk=requisition_id)
    )
    if requisition.status != PurchaseRequisition.Status.APPROVED:
        raise ValidationError("Approve the draft requisition before creating an order.")
    if not requisition.product.supplier:
        raise ValidationError("Assign a supplier to the product before ordering.")
    if requisition.quantity <= 0:
        raise ValidationError("Purchase order quantity must be positive.")
    order = PurchaseOrder.objects.create(
        requisition=requisition, supplier=requisition.product.supplier,
        quantity=requisition.quantity, unit_cost=requisition.product.unit_price,
        created_by=user,
    )
    requisition.status = PurchaseRequisition.Status.ORDERED
    requisition.save(update_fields=["status"])
    return order


@transaction.atomic
def receive_purchase_order(*, order_id, user=None):
    """Full quantity goods receipt only; partial receipts are outside the MVP."""
    order = (
        PurchaseOrder.objects.select_for_update()
        .select_related("requisition__product").get(pk=order_id)
    )
    if order.status != PurchaseOrder.Status.ORDERED:
        raise ValidationError("This purchase order has already been received.")
    # Order's one receipt is guarded by transaction plus the order status check.
    movement = record_stock_movement(
        product_id=order.requisition.product_id,
        movement_type=StockMovement.MovementType.IN,
        quantity=order.quantity,
        user=user, note=f"Goods receipt for PO-{order.pk}",
    )
    order.status = PurchaseOrder.Status.RECEIVED
    order.received_at = timezone.now()
    order.received_by = user
    order.save(update_fields=["status", "received_at", "received_by"])
    requisition = order.requisition
    requisition.status = PurchaseRequisition.Status.FULFILLED
    requisition.save(update_fields=["status"])
    # If stock is still below target after receipt, a new request can now be raised.
    product = Product.objects.get(pk=requisition.product_id)
    create_requisition_if_needed(product, user=user)
    return movement
