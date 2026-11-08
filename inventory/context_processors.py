from django.db.models import F
from .models import Product


def navigation(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "nav_low_stock_count": Product.objects.filter(
            is_active=True, current_stock__lte=F("reorder_level")
        ).count()
    }
