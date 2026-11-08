from django.contrib import admin
from .models import (
    Category, Supplier, Warehouse, Product,
    StockMovement, PurchaseRequisition, PurchaseOrder,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "phone"]
    search_fields = ["name"]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "location"]
    search_fields = ["code", "name"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "current_stock", "reorder_level", "target_stock", "warehouse", "supplier"]
    list_filter = ["category", "warehouse", "is_active"]
    search_fields = ["sku", "name"]
    readonly_fields = ["current_stock", "created_at", "updated_at"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["product", "movement_type", "quantity", "created_by", "created_at"]
    list_filter = ["movement_type", "created_at"]
    readonly_fields = ["product", "movement_type", "quantity", "note", "created_by", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PurchaseRequisition)
class PurchaseRequisitionAdmin(admin.ModelAdmin):
    list_display = ["id", "product", "quantity", "status", "created_at"]
    list_filter = ["status", "created_at"]
    readonly_fields = ["product", "quantity", "status", "reason", "created_by", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["id", "requisition", "supplier", "quantity", "status", "created_at"]
    list_filter = ["status"]
    readonly_fields = ["requisition", "supplier", "quantity", "unit_cost", "status", "created_by", "created_at", "received_by", "received_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
