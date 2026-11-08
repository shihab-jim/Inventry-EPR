"""AI-powered inventory assistant using Google Gemini API."""
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import F, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def _decimal_default(obj):
    """JSON serializer for Decimal objects."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def gather_inventory_context():
    """Collect current inventory metrics to feed as context to the AI model."""
    from .models import (
        Product, StockMovement, PurchaseRequisition, PurchaseOrder,
        Warehouse, Supplier, Category,
    )

    products = Product.objects.filter(is_active=True)
    all_products = Product.objects.all()
    now = timezone.now()
    last_7_days = now - timedelta(days=7)
    last_30_days = now - timedelta(days=30)

    # --- KPI summary ---
    total_products = products.count()
    in_stock = products.filter(current_stock__gt=F("reorder_level")).count()
    low_stock = products.filter(current_stock__gt=0, current_stock__lte=F("reorder_level"))
    low_stock_count = low_stock.count()
    out_of_stock = products.filter(current_stock=0).count()
    total_units = products.aggregate(t=Sum("current_stock"))["t"] or 0
    inventory_value = products.aggregate(
        t=Sum(F("unit_price") * F("current_stock"))
    )["t"] or 0

    # --- Product details ---
    product_details = list(
        all_products.select_related("category", "supplier", "warehouse")
        .values(
            "sku", "name", "current_stock", "reorder_level", "target_stock",
            "unit_price", "is_active",
            category_name=F("category__name"),
            supplier_name=F("supplier__name"),
            warehouse_name=F("warehouse__name"),
        )[:50]
    )

    # --- Low stock alerts ---
    low_stock_items = list(
        low_stock.values("sku", "name", "current_stock", "reorder_level", "target_stock")
    )

    # --- Out of stock ---
    out_of_stock_items = list(
        products.filter(current_stock=0).values("sku", "name")
    )

    # --- Recent movements (last 7 days) ---
    recent_movements = list(
        StockMovement.objects.filter(created_at__gte=last_7_days)
        .select_related("product")
        .values("product__sku", "product__name", "movement_type", "quantity", "note", "created_at")
        .order_by("-created_at")[:30]
    )
    # Convert datetimes for JSON
    for m in recent_movements:
        m["created_at"] = m["created_at"].isoformat()

    # Movement totals
    movements_7d = StockMovement.objects.filter(created_at__gte=last_7_days)
    inbound_7d = movements_7d.filter(movement_type="IN").aggregate(t=Sum("quantity"))["t"] or 0
    outbound_7d = movements_7d.filter(movement_type="OUT").aggregate(t=Sum("quantity"))["t"] or 0

    movements_30d = StockMovement.objects.filter(created_at__gte=last_30_days)
    inbound_30d = movements_30d.filter(movement_type="IN").aggregate(t=Sum("quantity"))["t"] or 0
    outbound_30d = movements_30d.filter(movement_type="OUT").aggregate(t=Sum("quantity"))["t"] or 0

    # --- Open requisitions ---
    open_statuses = ["DRAFT", "APPROVED", "ORDERED"]
    open_requisitions = list(
        PurchaseRequisition.objects.filter(status__in=open_statuses)
        .select_related("product")
        .values("id", "product__sku", "product__name", "quantity", "status", "reason", "created_at")
    )
    for r in open_requisitions:
        r["created_at"] = r["created_at"].isoformat()

    # --- Recent purchase orders ---
    recent_orders = list(
        PurchaseOrder.objects.all()
        .select_related("requisition__product", "supplier")
        .values(
            "id", "status", "quantity", "unit_cost",
            "requisition__product__sku", "requisition__product__name",
            supplier_name=F("supplier__name"),
        )[:20]
    )

    # --- Warehouse and supplier counts ---
    warehouse_count = Warehouse.objects.count()
    supplier_count = Supplier.objects.count()
    category_count = Category.objects.count()

    # --- Top products by stock value ---
    top_by_value = list(
        products.annotate(
            stock_value=F("unit_price") * F("current_stock")
        ).order_by("-stock_value").values("sku", "name", "current_stock", "unit_price", "stock_value")[:5]
    )

    context = {
        "summary": {
            "total_active_products": total_products,
            "in_stock": in_stock,
            "low_stock": low_stock_count,
            "out_of_stock": out_of_stock,
            "total_units_in_inventory": total_units,
            "total_inventory_value": inventory_value,
            "warehouses": warehouse_count,
            "suppliers": supplier_count,
            "categories": category_count,
        },
        "movement_summary": {
            "last_7_days": {"inbound": inbound_7d, "outbound": outbound_7d},
            "last_30_days": {"inbound": inbound_30d, "outbound": outbound_30d},
        },
        "all_products": product_details,
        "low_stock_items": low_stock_items,
        "out_of_stock_items": out_of_stock_items,
        "recent_movements": recent_movements,
        "open_requisitions": open_requisitions,
        "recent_purchase_orders": recent_orders,
        "top_products_by_value": top_by_value,
    }
    return context


def get_system_prompt():
    """Return the system instructions for the AI inventory assistant."""
    return """You are SmartStock AI Assistant, an intelligent inventory management assistant for the SmartStock ERP system.

Your role:
- Help users understand their inventory status, stock levels, and supply chain operations.
- Answer questions about products, stock movements, requisitions, and purchase orders.
- Provide actionable insights and recommendations based on the inventory data.
- Alert users to potential issues (low stock, out-of-stock items, pending requisitions).

Guidelines:
- Be concise but thorough. Use bullet points and numbers for clarity.
- When referencing products, include both the SKU and name.
- Format currency values with 2 decimal places.
- If you don't have enough data to answer a question, say so honestly.
- Provide helpful suggestions when appropriate (e.g., "You may want to reorder X").
- Use a professional yet friendly tone appropriate for a business context.
- When asked for analysis, provide data-driven insights.
- Use simple markdown for formatting (bold, bullet points, etc.) but avoid complex HTML.
"""


def _local_fallback_answer(user_message, ctx):
    """
    Intelligent local analytics response when no Gemini API key is provided.
    Ensures the chatbot always works for demo & presentation purposes.
    """
    msg = user_message.lower()
    summary = ctx["summary"]

    if any(k in msg for k in ["overview", "status", "summary", "health", "how is", "state"]):
        return (
            f"📊 **SmartStock Inventory Overview** *(Offline Analytics Mode)*:\n\n"
            f"• **Active Products:** {summary['total_active_products']}\n"
            f"• **Total Units in Stock:** {summary['total_units_in_inventory']:,}\n"
            f"• **Total Inventory Value:** ${summary['total_inventory_value']:,.2f}\n"
            f"• **In Stock:** {summary['in_stock']} items\n"
            f"• **Low Stock Alert:** {summary['low_stock']} items\n"
            f"• **Out of Stock:** {summary['out_of_stock']} items\n"
            f"• **Warehouses:** {summary['warehouses']} | **Suppliers:** {summary['suppliers']}\n\n"
            f"💡 *Tip: Add your `GEMINI_API_KEY` in `settings.py` to enable full natural language conversational AI.*"
        )

    if any(k in msg for k in ["low", "shortage", "alert", "out of stock", "reorder", "running low"]):
        low_items = ctx.get("low_stock_items", [])
        out_items = ctx.get("out_of_stock_items", [])
        lines = ["⚠️ **Stock Alert Analysis** *(Offline Analytics Mode)*:\n"]
        if out_items:
            lines.append("**Out of Stock (Urgent):**")
            for item in out_items:
                lines.append(f"• `{item['sku']}` — {item['name']} (0 units)")
        if low_items:
            lines.append("\n**Low Stock Items (Below Reorder Level):**")
            for item in low_items:
                needed = max(0, item['target_stock'] - item['current_stock'])
                lines.append(
                    f"• `{item['sku']}` — {item['name']}: **{item['current_stock']} units** "
                    f"(Reorder level: {item['reorder_level']}, Target: {item['target_stock']}, Need: +{needed})"
                )
        if not low_items and not out_items:
            lines.append("✅ All active products currently have sufficient stock above reorder thresholds.")
        lines.append(f"\n💡 *Recommendation: Review the **Requisitions** tab to approve draft purchase requests.*")
        return "\n".join(lines)

    if any(k in msg for k in ["top", "value", "valuable", "worth", "expensive"]):
        top_items = ctx.get("top_products_by_value", [])
        lines = [f"💰 **Top Products by Inventory Value** (Total: ${summary['total_inventory_value']:,.2f}):\n"]
        for i, item in enumerate(top_items, 1):
            val = float(item['stock_value'])
            lines.append(
                f"{i}. `{item['sku']}` — **{item['name']}**\n"
                f"   • {item['current_stock']} units @ ${float(item['unit_price']):,.2f} = **${val:,.2f}**"
            )
        return "\n".join(lines)

    if any(k in msg for k in ["movement", "inbound", "outbound", "recent", "history", "trend"]):
        mov_7d = ctx["movement_summary"]["last_7_days"]
        mov_list = ctx.get("recent_movements", [])[:5]
        lines = [
            "📦 **Stock Movement Summary (Last 7 Days)**:\n",
            f"• **Inbound (Received):** +{mov_7d['inbound']} units",
            f"• **Outbound (Dispatched):** -{mov_7d['outbound']} units\n",
            "**Recent Transactions:**"
        ]
        for m in mov_list:
            sign = "+" if m["movement_type"] == "IN" else "-"
            lines.append(f"• `{m['product__sku']}`: {sign}{m['quantity']} units ({m['movement_type']}) — *{m['note'] or 'No note'}*")
        return "\n".join(lines)

    if any(k in msg for k in ["requisition", "order", "purchase", "po", "supplier"]):
        reqs = ctx.get("open_requisitions", [])
        orders = ctx.get("recent_purchase_orders", [])
        lines = [
            f"📋 **Procurement Status**:\n",
            f"• **Open Requisitions:** {len(reqs)} pending",
            f"• **Recent Purchase Orders:** {len(orders)} on record\n"
        ]
        if reqs:
            lines.append("**Pending Requisitions:**")
            for r in reqs[:4]:
                lines.append(f"• PR-#{r['id']}: `{r['product__sku']}` — {r['quantity']} units ({r['status']})")
        return "\n".join(lines)

    # General fallback
    return (
        f"🤖 **SmartStock AI Assistant** *(Local Mode)*\n\n"
        f"I'm operating in **Local Analytics Mode** because no `GEMINI_API_KEY` is configured yet.\n\n"
        f"I can currently answer data queries like:\n"
        f"• *\"Give me an overview of my inventory status\"*\n"
        f"• *\"Which products are running low on stock?\"*\n"
        f"• *\"What are my top products by inventory value?\"*\n"
        f"• *\"Summarize recent stock movements\"*\n"
        f"• *\"Show procurement and purchase order status\"*\n\n"
        f"🔑 *To enable full conversational answers powered by Google Gemini, paste your API key in `smartstock/settings.py`.*"
    )


def _call_gemini_api(contents, system_instruction=None, timeout=12):
    """
    Direct REST call to Gemini API for fast, reliable execution on Windows.
    Tries gemini-3-flash-preview first (tested: ~2s), then gemini-3.8-flash.
    """
    import requests
    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        return None

    models = ["gemini-3-flash-preview", "gemini-3.8-flash"]
    payload = {"contents": contents}
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
            else:
                logger.warning("Gemini model %s returned status %s: %s", model, resp.status_code, resp.text[:200])
        except Exception as err:
            logger.warning("Gemini call for model %s failed: %s", model, err)
            continue
    return None


def ask_ai_assistant(user_message, conversation_history=None):
    """
    Send a user question to Gemini along with live inventory context.
    Falls back gracefully to intelligent local analytics if Gemini is offline or slow.
    """
    inventory_context = gather_inventory_context()
    api_key = getattr(settings, "GEMINI_API_KEY", "")

    # Fast check: If no API key configured, use local analytics
    if not api_key:
        return _local_fallback_answer(user_message, inventory_context)

    context_json = json.dumps(inventory_context, default=_decimal_default, indent=2)

    contents = []
    # Add recent history if available
    if conversation_history:
        for msg in conversation_history[-6:]:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

    # Add current question with live inventory context
    augmented = (
        f"Live SmartStock inventory metrics:\n```json\n{context_json}\n```\n\n"
        f"User question: {user_message}"
    )
    contents.append({"role": "user", "parts": [{"text": augmented}]})

    # Call Gemini REST API with 12s timeout
    reply = _call_gemini_api(contents, system_instruction=get_system_prompt(), timeout=12)
    if reply:
        return reply

    # If cloud call timed out or failed, provide immediate local analytics
    return _local_fallback_answer(user_message, inventory_context)


def generate_executive_report():
    """
    Generate an executive-level inventory audit and intelligence briefing.
    Uses Gemini when available, or a structured local report generator.
    """
    ctx = gather_inventory_context()
    api_key = getattr(settings, "GEMINI_API_KEY", "")

    if not api_key:
        return _local_executive_report(ctx)

    prompt = f"""You are the Chief Supply Chain Analyst for SmartStock ERP.
Generate a comprehensive, executive-level Inventory Audit & Strategy Briefing based on this live operational data:

```json
{json.dumps(ctx, default=_decimal_default, indent=2)}
```

Structure your report into these distinct sections:
# 📋 Executive Inventory Audit & Strategic Briefing

### 1. Overall Health Score & Executive Summary
- Provide an overall Inventory Health Score (out of 100) with a brief justification.
- Summary of capital exposure and active stock units.

### 2. Immediate Operational Risks
- Critical stockout warnings and products with zero or dangerously low balances.
- Immediate actions needed to prevent supply disruption.

### 3. Working Capital & Valuation Insights
- Analysis of top capital-consuming items.
- Identification of high-value stock vs. low-turnover risk.

### 4. Stock Velocity & Movement Trends (7-Day & 30-Day)
- Inbound vs. Outbound flow dynamics.
- Replenishment pipeline evaluation (open requisitions vs purchase orders).

### 5. Strategic Recommendations for Management
- Exactly 3 prioritised, actionable recommendations for the operations team.

Make it professional, data-driven, and ready for presentation to executive leadership. Use markdown formatting with bold metrics and clean bullet points.
"""
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    report = _call_gemini_api(contents, system_instruction=get_system_prompt(), timeout=16)
    if report:
        return report

    return _local_executive_report(ctx)


def _local_executive_report(ctx):
    """Fallback executive report generated offline from local database metrics."""
    s = ctx["summary"]
    low = ctx.get("low_stock_items", [])
    out = ctx.get("out_of_stock_items", [])
    top = ctx.get("top_products_by_value", [])
    mov = ctx["movement_summary"]["last_7_days"]

    # Calculate basic health score
    total = s["total_active_products"] or 1
    penalty = (len(out) * 15) + (len(low) * 8)
    health_score = max(10, min(95, 100 - penalty))

    report = f"""# 📋 Executive Inventory Audit & Strategic Briefing

### 1. Overall Health Score & Executive Summary
- **Inventory Health Score:** **{health_score} / 100**
- **Active SKUs Managed:** {s['total_active_products']} items across {s['warehouses']} warehouse(s)
- **Total Physical Units on Hand:** {s['total_units_in_inventory']:,} units
- **Total Working Capital Tied in Stock:** **${s['total_inventory_value']:,.2f}**

### 2. Immediate Operational Risks
"""
    if out:
        report += "- **⚠️ Stockouts Detected:** " + ", ".join([f"`{i['sku']}` ({i['name']})" for i in out]) + "\n"
    if low:
        report += f"- **⚠️ Shortage Alerts:** {len(low)} product(s) currently below their defined safety reorder thresholds.\n"
    if not out and not low:
        report += "- **✅ Healthy Stock:** All catalog products are currently above their reorder points.\n"

    report += f"""
### 3. Working Capital & Valuation Insights
- **Concentration:** Top items represent the vast majority of capital commitment.
"""
    for i, item in enumerate(top[:3], 1):
        report += f"  {i}. `{item['sku']}` ({item['name']}): **${float(item['stock_value']):,.2f}** ({item['current_stock']} units)\n"

    report += f"""
### 4. Stock Velocity & Movement Trends (Last 7 Days)
- **Inbound Receipts:** +{mov['inbound']} units received
- **Outbound Dispatches:** -{mov['outbound']} units shipped
- **Open Purchase Requisitions:** {len(ctx.get('open_requisitions', []))} pending review

### 5. Strategic Recommendations for Management
1. **Accelerate Requisitions:** Convert open low-stock draft requisitions into purchase orders to replenish critical shortages.
2. **Review High-Value Reorder Points:** Audit inventory limits on top capital-consuming lines to free up working capital.
3. **Supplier Lead Time Monitoring:** Align replenishment cycles with supplier delivery commitments to prevent future stockouts.
"""
    return report

