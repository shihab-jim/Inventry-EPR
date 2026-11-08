"""Models for the SmartStock educational ERP demo.

The MVP records one warehouse per product, not multiple warehouse balances.
Current stock must be changed only by the audited inventory service.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=35, blank=True)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=180, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField("SKU", max_length=40, unique=True)
    name = models.CharField(max_length=160)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_stock = models.PositiveIntegerField(default=0, editable=False)
    reorder_level = models.PositiveIntegerField(default=10)
    target_stock = models.PositiveIntegerField(default=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.reorder_level is not None and self.target_stock is not None:
            if self.target_stock <= self.reorder_level:
                raise ValidationError({"target_stock": "Target stock must exceed reorder level."})
        if self.unit_price is not None and self.unit_price < 0:
            raise ValidationError({"unit_price": "Unit price cannot be negative."})

    @property
    def needs_reorder(self):
        return self.is_active and self.current_stock <= self.reorder_level

    @property
    def stock_status(self):
        if not self.is_active:
            return "Inactive"
        if self.current_stock == 0:
            return "Out of Stock"
        if self.needs_reorder:
            return "Low Stock"
        return "In Stock"

    @property
    def suggested_reorder_qty(self):
        return max(0, self.target_stock - self.current_stock) if self.needs_reorder else 0

    def __str__(self):
        return f"{self.sku} - {self.name}"


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=3, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.movement_type} {self.quantity} x {self.product.sku}"


class PurchaseRequisition(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        APPROVED = "APPROVED", "Approved"
        ORDERED = "ORDERED", "Ordered"
        REJECTED = "REJECTED", "Rejected"
        FULFILLED = "FULFILLED", "Fulfilled"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="requisitions")
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    reason = models.CharField(max_length=240, default="Automatic low-stock reorder")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(status__in=["DRAFT", "APPROVED", "ORDERED"]),
                name="one_open_requisition_per_product",
            )
        ]

    def __str__(self):
        return f"PR-{self.pk} for {self.product.sku}"


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        ORDERED = "ORDERED", "Ordered"
        RECEIVED = "RECEIVED", "Received"

    requisition = models.OneToOneField(
        PurchaseRequisition, on_delete=models.PROTECT, related_name="purchase_order"
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ORDERED)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders_created"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders_received"
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def product(self):
        return self.requisition.product

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost

    def __str__(self):
        return f"PO-{self.pk} for PR-{self.requisition_id}"
