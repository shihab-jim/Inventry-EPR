"""Create repeatable demo records with logged stock movements.

Demo data is deliberately synthetic and labelled as such.
Existing SKUs are never overwritten, so rerunning is safe.
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from inventory.models import Category, Product, Supplier, Warehouse, StockMovement
from inventory.services import record_stock_movement


class Command(BaseCommand):
    help = "Seed synthetic warehouse, supplier, product and transaction records (safe to rerun)."

    def handle(self, *args, **kwargs):
        categories = {
            name: Category.objects.get_or_create(name=name)[0]
            for name in ["Electronics", "Apparel", "Accessories", "Office Supplies"]
        }
        suppliers = {
            name: Supplier.objects.get_or_create(name=name, defaults={"email": email, "phone": phone})[0]
            for name, email, phone in [
                ("Nexa Trading Ltd", "hello@nexa.example", "01700000001"),
                ("Metro Office Supplies", "info@metro.example", "01700000002"),
                ("Fashion House Ltd", "orders@fashion.example", "01700000003"),
            ]
        }
        warehouses = {}
        for code, name, location in [
            ("WH-A", "Warehouse A", "Dhaka"),
            ("WH-B", "Warehouse B", "Savar"),
            ("WH-C", "Warehouse C", "Gazipur"),
            ("WH-D", "Warehouse D", "Narayanganj"),
        ]:
            warehouses[code] = Warehouse.objects.get_or_create(
                code=code, defaults={"name": name, "location": location}
            )[0]

        # sku, name, category, supplier, warehouse, current_stock, reorder_point,
        # target_stock, unit_price, demo issue quantity, incoming-day-offset
        examples = [
            ("HP-401", "Wireless Headphones", "Electronics", "Nexa Trading Ltd", "WH-A", 12, 20, 120, "2400.00", 35, 6),
            ("DR-552", "Women's Pleated Dress", "Apparel", "Fashion House Ltd", "WH-B", 145, 30, 220, "1750.00", 38, 5),
            ("HB-218", "Leather Handbag", "Accessories", "Fashion House Ltd", "WH-C", 0, 10, 80, "3200.00", 25, 4),
            ("SW-309", "Graphic Sweatshirt", "Apparel", "Fashion House Ltd", "WH-D", 75, 40, 150, "1250.00", 45, 6),
            ("KD-114", "Kids Party Dress", "Apparel", "Fashion House Ltd", "WH-B", 22, 25, 100, "1800.00", 25, 3),
            ("USB-001", "USB-C Cable", "Electronics", "Nexa Trading Ltd", "WH-A", 18, 20, 75, "250.00", 27, 4),
            ("PAP-001", "A4 Printer Paper", "Office Supplies", "Metro Office Supplies", "WH-C", 30, 15, 100, "420.00", 35, 5),
            ("INK-001", "Printer Ink Cartridge", "Office Supplies", "Metro Office Supplies", "WH-C", 12, 5, 30, "1250.00", 8, 2),
            ("SP-801", "Bluetooth Speaker", "Electronics", "Nexa Trading Ltd", "WH-A", 55, 18, 100, "2900.00", 20, 3),
            ("NB-120", "Hardcover Notebook", "Office Supplies", "Metro Office Supplies", "WH-D", 220, 60, 300, "180.00", 60, 6),
        ]
        now = timezone.now()
        created_count = 0
        for sku, name, category, supplier, warehouse, balance, reorder, target, price, issue, day_offset in examples:
            product, created = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name, "category": categories[category],
                    "supplier": suppliers[supplier], "warehouse": warehouses[warehouse],
                    "reorder_level": reorder, "target_stock": target, "unit_price": price,
                },
            )
            if not created:
                continue
            created_count += 1
            incoming = record_stock_movement(
                product_id=product.pk, movement_type="IN", quantity=balance + issue,
                note="Demo: supplier delivery opening balance",
            )
            StockMovement.objects.filter(pk=incoming.pk).update(
                created_at=now - timedelta(days=day_offset, hours=2)
            )
            outgoing = record_stock_movement(
                product_id=product.pk, movement_type="OUT", quantity=issue,
                note="Demo: issued to operations",
            )
            StockMovement.objects.filter(pk=outgoing.pk).update(
                created_at=now - timedelta(days=max(day_offset - 2, 0), hours=1)
            )
            self.stdout.write(self.style.SUCCESS(f"Created {sku} with {balance} units"))

        self.stdout.write(self.style.SUCCESS(
            f"Demo ready: {created_count} new products. Existing records unchanged. "
            "Try approving a draft requisition, creating a PO, then receiving goods."
        ))

        # Create demo superuser on fresh database deployments
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if not User.objects.filter(is_superuser=True).exists():
            admin_user = User.objects.create_superuser(
                username="admin",
                email="admin@smartstock.example",
                password="adminpassword123",
            )
            admin_user.first_name = "Admin"
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created default superuser: admin / adminpassword123"))

        if not User.objects.filter(username="shihab").exists():
            shihab = User.objects.create_superuser(
                username="shihab",
                email="shihab@example.com",
                password="adminpassword123",
            )
            shihab.first_name = "Shihab"
            shihab.save()
            self.stdout.write(self.style.SUCCESS("Created superuser: shihab / adminpassword123"))
