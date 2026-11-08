from django.urls import path
from . import views

app_name = "inventory"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("products/", views.product_list, name="products"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/stock/", views.stock_movement_create, name="stock_movement"),
    path("movements/", views.stock_movement_list, name="movements"),
    path("warehouses/", views.warehouse_list, name="warehouses"),
    path("warehouses/new/", views.warehouse_create, name="warehouse_create"),
    path("suppliers/", views.supplier_list, name="suppliers"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("reorder-rules/", views.reorder_rules, name="reorder_rules"),
    path("reorder-rules/<int:pk>/edit/", views.reorder_rule_edit, name="reorder_rule_edit"),
    path("reorder-rules/<int:pk>/generate/", views.reorder_generate, name="reorder_generate"),
    path("requisitions/", views.requisition_list, name="requisitions"),
    path("requisitions/<int:pk>/<str:action>/", views.requisition_action, name="requisition_action"),
    path("purchase-orders/", views.purchase_order_list, name="purchase_orders"),
    path("purchase-orders/from-requisition/<int:pk>/", views.purchase_order_create, name="purchase_order_create"),
    path("purchase-orders/<int:pk>/receive/", views.purchase_order_receive, name="purchase_order_receive"),
    path("reports/", views.reports, name="reports"),
    path("export/<str:kind>/", views.export_csv, name="export_csv"),
    path("settings/", views.profile_settings, name="settings"),
    path("ai/chat/", views.ai_chat, name="ai_chat"),
    path("ai/report/", views.ai_report, name="ai_report"),
]
