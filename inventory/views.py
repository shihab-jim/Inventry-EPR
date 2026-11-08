"""Views for the independent SmartStock ERP internship demo."""
import csv
import json
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    ProductForm, StockMovementForm, SupplierForm, WarehouseForm,
    ReorderRuleForm, ProfileForm,
)
from .models import (
    Product, Supplier, Warehouse, PurchaseRequisition, PurchaseOrder,
    StockMovement,
)
from .services import (
    record_stock_movement, create_requisition_if_needed, transition_requisition,
    create_purchase_order, receive_purchase_order,
)


staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url="inventory:dashboard")
OPEN_STATUSES = [
    PurchaseRequisition.Status.DRAFT,
    PurchaseRequisition.Status.APPROVED,
    PurchaseRequisition.Status.ORDERED,
]


def active_products():
    return Product.objects.filter(is_active=True)


def stock_value_expression():
    return ExpressionWrapper(
        F("unit_price") * F("current_stock"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )


@login_required
def dashboard(request):
    products = active_products()
    low_stock = products.filter(current_stock__lte=F("reorder_level"))
    today = timezone.localdate()
    dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
    movements = StockMovement.objects.filter(created_at__date__gte=dates[0])
    movement_counts = defaultdict(lambda: {"IN": 0, "OUT": 0})
    for movement in movements.values("created_at", "movement_type", "quantity"):
        day = timezone.localtime(movement["created_at"]).date()
        movement_counts[day][movement["movement_type"]] += movement["quantity"]

    watchlist = list(
        low_stock.select_related("supplier", "warehouse", "category")
        .order_by("current_stock", "name")[:5]
    )
    existing = {
        req.product_id: req
        for req in PurchaseRequisition.objects.filter(
            product_id__in=[p.pk for p in watchlist], status__in=OPEN_STATUSES
        )
    }
    recommendations = [
        {
            "product": p,
            "quantity": max(p.target_stock - p.current_stock, 0),
            "request": existing.get(p.pk),
        }
        for p in watchlist
    ]
    context = {
        "product_count": products.count(),
        "in_stock_count": products.filter(current_stock__gt=F("reorder_level")).count(),
        "low_stock_count": low_stock.filter(current_stock__gt=0).count(),
        "out_stock_count": products.filter(current_stock=0).count(),
        "total_units": products.aggregate(total=Sum("current_stock"))["total"] or 0,
        "inventory_value": products.aggregate(total=Sum(stock_value_expression()))["total"] or 0,
        "open_request_count": PurchaseRequisition.objects.filter(status__in=OPEN_STATUSES).count(),
        "recent_products": products.select_related("category", "warehouse").order_by("-updated_at")[:7],
        "recent_movements": StockMovement.objects.select_related("product")[:5],
        "recommendations": recommendations,
        "movement_chart": {
            "labels": [date.strftime("%a %d") for date in dates],
            "received": [movement_counts[d]["IN"] for d in dates],
            "issued": [movement_counts[d]["OUT"] for d in dates],
        },
    }
    return render(request, "inventory/dashboard.html", context)


def filter_products(request):
    products = Product.objects.select_related("category", "supplier", "warehouse")
    search = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "")
    warehouse = request.GET.get("warehouse", "")
    if search:
        products = products.filter(Q(name__icontains=search) | Q(sku__icontains=search))
    if status == "in":
        products = products.filter(is_active=True, current_stock__gt=F("reorder_level"))
    elif status == "low":
        products = products.filter(
            is_active=True, current_stock__gt=0, current_stock__lte=F("reorder_level")
        )
    elif status == "out":
        products = products.filter(is_active=True, current_stock=0)
    elif status == "inactive":
        products = products.filter(is_active=False)
    if warehouse.isdecimal():
        products = products.filter(warehouse_id=int(warehouse))
    return products.order_by("name")


@login_required
def product_list(request):
    products = filter_products(request)
    return render(request, "inventory/product_list.html", {
        "products": products[:150],
        "total_results": products.count(),
        "warehouses": Warehouse.objects.all(),
        "search": request.GET.get("q", ""),
        "selected_status": request.GET.get("status", ""),
        "selected_warehouse": request.GET.get("warehouse", ""),
    })


@login_required
@staff_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        # Do not create a draft before the user records opening stock.
        messages.success(request, "Product added. Use Stock In to set its opening quantity.")
        return redirect("inventory:products")
    return render(request, "inventory/product_form.html", {"form": form, "title": "Add product"})


@login_required
@staff_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            product = form.save()
            create_requisition_if_needed(product, user=request.user)
        messages.success(request, "Product updated successfully.")
        return redirect("inventory:products")
    return render(request, "inventory/product_form.html", {"form": form, "title": "Edit product"})


@login_required
@staff_required
def stock_movement_create(request, pk):
    product = get_object_or_404(Product, pk=pk, is_active=True)
    form = StockMovementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            record_stock_movement(
                product_id=product.pk,
                movement_type=form.cleaned_data["movement_type"],
                quantity=form.cleaned_data["quantity"],
                note=form.cleaned_data["note"], user=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, "Stock recorded. Automatic reorder rule checked.")
            return redirect("inventory:products")
    return render(request, "inventory/stock_form.html", {"product": product, "form": form})


@login_required
def stock_movement_list(request):
    movements = StockMovement.objects.select_related("product", "created_by", "product__warehouse")
    selected_type = request.GET.get("type", "")
    if selected_type in StockMovement.MovementType.values:
        movements = movements.filter(movement_type=selected_type)
    return render(request, "inventory/movements.html", {
        "movements": movements[:200], "selected_type": selected_type,
    })


@login_required
def requisition_list(request):
    qs = PurchaseRequisition.objects.select_related("product", "product__supplier", "created_by")
    return render(request, "inventory/requisition_list.html", {
        "requisitions": qs[:150],
    })


@login_required
@staff_required
def requisition_action(request, pk, action):
    if request.method != "POST":
        return redirect("inventory:requisitions")
    get_object_or_404(PurchaseRequisition, pk=pk)
    try:
        transition_requisition(requisition_id=pk, action=action)
        messages.success(request, "Requisition approved." if action == "approve" else "Requisition rejected.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:requisitions")


@login_required
@staff_required
def reorder_generate(request, pk):
    if request.method != "POST":
        return redirect("inventory:dashboard")
    product = get_object_or_404(Product, pk=pk, is_active=True)
    with transaction.atomic():
        requisition = create_requisition_if_needed(product, user=request.user)
    if requisition:
        messages.success(request, f"Draft PR-{requisition.pk} created.")
    else:
        messages.info(request, "No new request: stock is sufficient or an open request already exists.")
    return redirect("inventory:requisitions")


@login_required
@staff_required
def purchase_order_create(request, pk):
    if request.method != "POST":
        return redirect("inventory:requisitions")
    get_object_or_404(PurchaseRequisition, pk=pk)
    try:
        order = create_purchase_order(requisition_id=pk, user=request.user)
        messages.success(request, f"PO-{order.pk} created and sent to order queue.")
        return redirect("inventory:purchase_orders")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    except Exception as exc:
        messages.error(request, f"Could not create purchase order: {exc}")
    return redirect("inventory:requisitions")


@login_required
def purchase_order_list(request):
    orders = PurchaseOrder.objects.select_related(
        "supplier", "requisition__product", "created_by"
    )
    return render(request, "inventory/orders.html", {"orders": orders[:150]})


@login_required
@staff_required
def purchase_order_receive(request, pk):
    if request.method != "POST":
        return redirect("inventory:purchase_orders")
    get_object_or_404(PurchaseOrder, pk=pk)
    try:
        receive_purchase_order(order_id=pk, user=request.user)
        messages.success(request, f"PO-{pk} received. Inventory balance updated.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    except Exception as exc:
        messages.error(request, f"Could not receive goods: {exc}")
    return redirect("inventory:purchase_orders")


@login_required
def warehouse_list(request):
    warehouses = Warehouse.objects.all()
    return render(request, "inventory/warehouses.html", {"warehouses": warehouses})


@login_required
@staff_required
def warehouse_create(request):
    form = WarehouseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Warehouse added.")
        return redirect("inventory:warehouses")
    return render(request, "inventory/simple_form.html", {"form": form, "title": "Add warehouse", "back_url": "inventory:warehouses"})


@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all()
    return render(request, "inventory/suppliers.html", {"suppliers": suppliers})


@login_required
@staff_required
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier added.")
        return redirect("inventory:suppliers")
    return render(request, "inventory/simple_form.html", {"form": form, "title": "Add supplier", "back_url": "inventory:suppliers"})


@login_required
def reorder_rules(request):
    return render(request, "inventory/reorder_rules.html", {
        "products": Product.objects.select_related("supplier").filter(is_active=True)[:150]
    })


@login_required
@staff_required
def reorder_rule_edit(request, pk):
    product = get_object_or_404(Product, pk=pk, is_active=True)
    form = ReorderRuleForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            product = form.save()
            create_requisition_if_needed(product, user=request.user)
        messages.success(request, "Reorder rule saved and inventory rechecked.")
        return redirect("inventory:reorder_rules")
    return render(request, "inventory/simple_form.html", {
        "form": form, "title": f"Reorder rule: {product.sku}",
        "back_url": "inventory:reorder_rules",
    })


@login_required
def reports(request):
    products = active_products()
    last_month = timezone.now() - timedelta(days=30)
    movements = StockMovement.objects.filter(created_at__gte=last_month)
    inbound = movements.filter(movement_type="IN").aggregate(total=Sum("quantity"))["total"] or 0
    outbound = movements.filter(movement_type="OUT").aggregate(total=Sum("quantity"))["total"] or 0
    return render(request, "inventory/reports.html", {
        "active_products": products.count(),
        "inventory_value": products.aggregate(total=Sum(stock_value_expression()))["total"] or 0,
        "inbound": inbound, "outbound": outbound,
        "out_stock": products.filter(current_stock=0).count(),
    })


def csv_safe(value):
    """Avoid spreadsheet formula injection when opening a CSV in Excel."""
    result = str(value if value is not None else "")
    if result.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + result
    return result


@login_required
def export_csv(request, kind):
    if kind not in {"products", "movements"}:
        return redirect("inventory:reports")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="smartstock-{kind}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    if kind == "products":
        writer.writerow(["SKU", "Name", "Category", "Supplier", "Warehouse", "Units", "Reorder Level", "Target Stock", "Status", "Unit Price"])
        for p in filter_products(request):
            writer.writerow([csv_safe(p.sku), csv_safe(p.name), csv_safe(p.category or ""),
                             csv_safe(p.supplier or ""), csv_safe(p.warehouse or ""),
                             p.current_stock, p.reorder_level, p.target_stock, p.stock_status,
                             p.unit_price])
    else:
        writer.writerow(["Timestamp", "SKU", "Product", "Movement", "Quantity", "Note", "User"])
        for m in StockMovement.objects.select_related("product", "created_by").all()[:5000]:
            writer.writerow([m.created_at.isoformat(), csv_safe(m.product.sku),
                             csv_safe(m.product.name), m.get_movement_type_display(),
                             m.quantity, csv_safe(m.note), csv_safe(m.created_by or "")])
    return response


@login_required
def profile_settings(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("inventory:settings")
    return render(request, "inventory/simple_form.html", {
        "form": form, "title": "Profile settings", "back_url": "inventory:dashboard"
    })


# ---------------------------------------------------------------------------
#  AI Inventory Assistant
# ---------------------------------------------------------------------------

@login_required
@require_POST
def ai_chat(request):
    """AJAX endpoint for the AI inventory assistant."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    user_message = body.get("message", "").strip()
    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)
    if len(user_message) > 1000:
        return JsonResponse({"error": "Message is too long (max 1000 characters)."}, status=400)

    conversation_history = body.get("history", [])

    from .ai_services import ask_ai_assistant
    reply = ask_ai_assistant(user_message, conversation_history=conversation_history)
    return JsonResponse({"reply": reply})


@login_required
@require_POST
def ai_report(request):
    """AJAX endpoint to generate a full executive AI audit report."""
    from .ai_services import generate_executive_report
    report_text = generate_executive_report()
    return JsonResponse({"report": report_text})
