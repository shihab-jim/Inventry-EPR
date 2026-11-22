"""Views for the independent SmartStock ERP internship demo."""
import csv
import json
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash, get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    ProductForm, StockMovementForm, SupplierForm, WarehouseForm,
    ReorderRuleForm, ProfileForm, AdminUserCreateForm,
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
        with transaction.atomic():
            product = form.save()
            req = create_requisition_if_needed(product, user=request.user)
        if req:
            messages.success(
                request,
                f"Product '{product.sku} - {product.name}' added. "
                f"Initial stock is 0; draft PR-{req.pk} automatically generated in Requisitions."
            )
        else:
            messages.success(request, f"Product '{product.sku} - {product.name}' added successfully.")
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
    return render(request, "inventory/product_form.html", {
        "form": form, "title": "Edit product", "product": product
    })


@login_required
@staff_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    name = product.name
    sku = product.sku
    has_history = product.movements.exists() or product.requisitions.exists()
    if has_history:
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
        messages.info(
            request,
            f"Product '{sku} - {name}' has transaction records and cannot be permanently deleted. "
            f"It has been archived/deactivated instead."
        )
    else:
        product.delete()
        messages.success(request, f"Product '{sku} - {name}' was deleted.")
    return redirect("inventory:products")


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
        except Exception as exc:
            form.add_error(None, f"Could not record movement: {exc}")
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
    open_product_ids = PurchaseRequisition.objects.filter(status__in=OPEN_STATUSES).values_list("product_id", flat=True)
    available_products = Product.objects.filter(is_active=True).exclude(id__in=open_product_ids).order_by("name")
    missing_pr_count = Product.objects.filter(
        is_active=True,
        current_stock__lte=F("reorder_level"),
    ).exclude(id__in=open_product_ids).count()
    return render(request, "inventory/requisition_list.html", {
        "requisitions": qs[:150],
        "available_products": available_products,
        "missing_pr_count": missing_pr_count,
    })


@login_required
@staff_required
@require_POST
def requisition_create(request):
    product_id = request.POST.get("product_id")
    quantity = request.POST.get("quantity")
    reason = request.POST.get("reason", "").strip() or "Manual purchase request"
    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid positive quantity.")
        return redirect("inventory:requisitions")

    product = get_object_or_404(Product, pk=product_id, is_active=True)
    if PurchaseRequisition.objects.filter(product=product, status__in=OPEN_STATUSES).exists():
        messages.error(request, f"An active requisition already exists for {product.sku} - {product.name}.")
        return redirect("inventory:requisitions")

    req = PurchaseRequisition.objects.create(
        product=product,
        quantity=quantity,
        reason=reason,
        created_by=request.user,
        status=PurchaseRequisition.Status.DRAFT,
    )
    messages.success(request, f"Draft PR-{req.pk} created for {product.sku} - {product.name}.")
    return redirect("inventory:requisitions")


@login_required
@staff_required
@require_POST
def requisitions_generate_missing(request):
    open_product_ids = PurchaseRequisition.objects.filter(status__in=OPEN_STATUSES).values_list("product_id", flat=True)
    low_stock_products = Product.objects.filter(
        is_active=True,
        current_stock__lte=F("reorder_level"),
    ).exclude(id__in=open_product_ids)
    created_count = 0
    with transaction.atomic():
        for product in low_stock_products:
            req = create_requisition_if_needed(product, user=request.user)
            if req:
                created_count += 1
    if created_count > 0:
        messages.success(request, f"Generated {created_count} draft requisition(s) for low-stock inventory.")
    else:
        messages.info(request, "All low-stock items already have active requisitions.")
    return redirect("inventory:requisitions")


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
    except Exception as exc:
        messages.error(request, f"Could not update requisition: {exc}")
    return redirect("inventory:requisitions")


@login_required
@staff_required
@require_POST
def requisition_delete(request, pk):
    requisition = get_object_or_404(PurchaseRequisition, pk=pk)
    if requisition.status not in {PurchaseRequisition.Status.DRAFT, PurchaseRequisition.Status.REJECTED}:
        messages.error(request, "Only draft or rejected requisitions can be deleted.")
        return redirect("inventory:requisitions")
    requisition.delete()
    messages.success(request, f"Requisition PR-{pk} was deleted.")
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
    warehouses = Warehouse.objects.annotate(product_count=Count("products"))
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
@staff_required
def warehouse_edit(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    form = WarehouseForm(request.POST or None, instance=warehouse)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Warehouse '{warehouse.name}' updated.")
        return redirect("inventory:warehouses")
    return render(request, "inventory/simple_form.html", {
        "form": form, "title": f"Edit Warehouse: {warehouse.code}", "back_url": "inventory:warehouses"
    })


@login_required
@staff_required
@require_POST
def warehouse_delete(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    name = warehouse.name
    warehouse.delete()
    messages.success(request, f"Warehouse '{name}' was deleted.")
    return redirect("inventory:warehouses")


@login_required
def supplier_list(request):
    suppliers = Supplier.objects.annotate(product_count=Count("products"))
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
@staff_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Supplier '{supplier.name}' updated.")
        return redirect("inventory:suppliers")
    return render(request, "inventory/simple_form.html", {
        "form": form, "title": f"Edit Supplier: {supplier.name}", "back_url": "inventory:suppliers"
    })


@login_required
@staff_required
@require_POST
def supplier_delete(request, pk):
    from django.db.models import ProtectedError
    supplier = get_object_or_404(Supplier, pk=pk)
    name = supplier.name
    try:
        supplier.delete()
        messages.success(request, f"Supplier '{name}' was deleted.")
    except ProtectedError:
        messages.error(
            request,
            f"Cannot delete supplier '{name}' because they have associated purchase orders."
        )
    return redirect("inventory:suppliers")


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
        qs = StockMovement.objects.select_related("product", "created_by").all()
        selected_type = request.GET.get("type", "")
        if selected_type in StockMovement.MovementType.values:
            qs = qs.filter(movement_type=selected_type)
        for m in qs[:5000]:
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
        return redirect("inventory:profile")
    return render(request, "inventory/simple_form.html", {
        "form": form, "title": "Profile settings", "back_url": "inventory:profile"
    })


@login_required
def user_profile(request):
    """Individual profile page with account info, stats, and admin user management."""
    user = request.user
    stats = {
        "movements": StockMovement.objects.filter(created_by=user).count(),
        "requisitions": PurchaseRequisition.objects.filter(created_by=user).count(),
        "purchase_orders": PurchaseOrder.objects.filter(created_by=user).count(),
    }
    context = {"stats": stats}
    if user.is_staff:
        User = get_user_model()
        context["all_users"] = User.objects.all().order_by("-date_joined")
        context["create_user_form"] = AdminUserCreateForm()
    return render(request, "inventory/profile.html", context)


@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def admin_user_create(request):
    """Admin-only action to insert a new user."""
    form = AdminUserCreateForm(request.POST)
    if form.is_valid():
        User = get_user_model()
        username = form.cleaned_data["username"].strip()
        email = form.cleaned_data.get("email", "").strip()
        first_name = form.cleaned_data.get("first_name", "").strip()
        last_name = form.cleaned_data.get("last_name", "").strip()
        password = form.cleaned_data["password"]
        role = form.cleaned_data["role"]

        try:
            new_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            if role == "staff":
                new_user.is_staff = True
                new_user.save(update_fields=["is_staff"])

            role_display = "Administrator" if role == "staff" else "Viewer"
            messages.success(request, f"User '{username}' created successfully as {role_display}.")
        except Exception as exc:
            messages.error(request, f"Could not create user: {exc}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field.title()}: {error}")
    return redirect("inventory:profile")


@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def admin_user_delete(request, pk):
    """Admin-only action to delete a user account."""
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)

    if target.pk == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return redirect("inventory:profile")

    if target.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only Super Admins can remove another Super Admin.")
        return redirect("inventory:profile")

    username = target.username
    target.delete()
    messages.success(request, f"User '{username}' was deleted successfully.")
    return redirect("inventory:profile")


@login_required
def change_password(request):
    """Password change view with styled form."""
    form = PasswordChangeForm(request.user, request.POST or None)
    # Apply Bootstrap styling to password form fields
    for field in form.fields.values():
        field.widget.attrs["class"] = "form-control"
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been updated successfully!")
        return redirect("inventory:profile")
    return render(request, "inventory/change_password.html", {"form": form})


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
