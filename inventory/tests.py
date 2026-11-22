from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Product, PurchaseRequisition, PurchaseOrder, StockMovement, Supplier
from .services import (
    record_stock_movement, transition_requisition,
    create_purchase_order, receive_purchase_order,
)


class InventoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="admin_demo", email="admin@example.com", password="StrongPass_123!"
        )
        self.viewer = User.objects.create_user(
            username="viewer_demo", password="StrongPass_123!"
        )
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.product = Product.objects.create(
            sku="TST-01", name="Test Cable", supplier=self.supplier, current_stock=25,
            reorder_level=15, target_stock=60, unit_price="25.00"
        )

    def test_stock_out_triggers_one_open_requisition(self):
        record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=12, user=self.admin)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 13)
        req = PurchaseRequisition.objects.get(product=self.product)
        self.assertEqual(req.quantity, 47)
        record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=1, user=self.admin)
        self.assertEqual(PurchaseRequisition.objects.filter(product=self.product).count(), 1)

    def test_out_of_stock_never_goes_negative(self):
        with self.assertRaises(ValidationError):
            record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=100)
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 25)
        self.assertFalse(StockMovement.objects.exists())

    def test_complete_procurement_workflow(self):
        record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=12, user=self.admin)
        req = PurchaseRequisition.objects.get(product=self.product)
        transition_requisition(requisition_id=req.pk, action="approve")
        po = create_purchase_order(requisition_id=req.pk, user=self.admin)
        req.refresh_from_db()
        self.assertEqual(req.status, PurchaseRequisition.Status.ORDERED)
        self.assertEqual(po.quantity, 47)
        receive_purchase_order(order_id=po.pk, user=self.admin)
        po.refresh_from_db()
        req.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.product.current_stock, 60)
        self.assertEqual(req.status, PurchaseRequisition.Status.FULFILLED)
        self.assertEqual(po.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_duplicate_order_creation_is_blocked(self):
        record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=12)
        req = PurchaseRequisition.objects.get(product=self.product)
        transition_requisition(requisition_id=req.pk, action="approve")
        create_purchase_order(requisition_id=req.pk, user=self.admin)
        with self.assertRaises(ValidationError):
            create_purchase_order(requisition_id=req.pk, user=self.admin)
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_receiving_order_twice_is_blocked(self):
        record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=12)
        req = PurchaseRequisition.objects.get(product=self.product)
        transition_requisition(requisition_id=req.pk, action="approve")
        po = create_purchase_order(requisition_id=req.pk, user=self.admin)
        receive_purchase_order(order_id=po.pk, user=self.admin)
        with self.assertRaises(ValidationError):
            receive_purchase_order(order_id=po.pk, user=self.admin)

    def test_viewer_cannot_approve_or_receive(self):
        self.client.force_login(self.viewer)
        response = self.client.post(reverse("inventory:requisition_action", args=[1, "approve"]))
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("inventory:purchase_order_receive", args=[1]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_dashboard_counts_and_navigation(self):
        self.client.force_login(self.admin)
        for page in ["dashboard", "products", "warehouses", "suppliers", "movements",
                     "requisitions", "purchase_orders", "reports", "reorder_rules", "settings"]:
            response = self.client.get(reverse(f"inventory:{page}"))
            self.assertEqual(response.status_code, 200, page)
        self.assertContains(self.client.get(reverse("inventory:dashboard")), "Stock Movement Trend")

    def test_product_csv(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("inventory:export_csv", args=["products"]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"TST-01", response.content)

    def test_dashboard_requires_login(self):
        self.assertEqual(self.client.get(reverse("inventory:dashboard")).status_code, 302)

    def test_user_profile_view_for_admin_and_viewer(self):
        # Admin profile
        self.client.force_login(self.admin)
        res_admin = self.client.get(reverse("inventory:profile"))
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "Super Admin")
        self.assertContains(res_admin, "User Management")

        # Viewer profile
        self.client.force_login(self.viewer)
        res_viewer = self.client.get(reverse("inventory:profile"))
        self.assertEqual(res_viewer.status_code, 200)
        self.assertContains(res_viewer, "Viewer")
        self.assertNotContains(res_viewer, "User Management")

    def test_admin_user_create_and_delete(self):
        User = get_user_model()
        self.client.force_login(self.admin)

        # Create new viewer user
        res = self.client.post(reverse("inventory:admin_user_create"), {
            "username": "new_staff_user",
            "first_name": "Test",
            "last_name": "Person",
            "email": "test@example.com",
            "password": "Password123!",
            "role": "staff",
        })
        self.assertEqual(res.status_code, 302)
        created_user = User.objects.get(username="new_staff_user")
        self.assertTrue(created_user.is_staff)

        # Delete user
        del_res = self.client.post(reverse("inventory:admin_user_delete", args=[created_user.pk]))
        self.assertEqual(del_res.status_code, 302)
        self.assertFalse(User.objects.filter(username="new_staff_user").exists())

        # Self-delete blocked
        self_del_res = self.client.post(reverse("inventory:admin_user_delete", args=[self.admin.pk]))
        self.assertEqual(self_del_res.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_viewer_cannot_manage_users(self):
        User = get_user_model()
        self.client.force_login(self.viewer)

        # Create user should be blocked (redirected)
        res = self.client.post(reverse("inventory:admin_user_create"), {
            "username": "hack_user",
            "password": "Password123!",
            "role": "staff",
        })
        self.assertEqual(res.status_code, 302)
        self.assertFalse(User.objects.filter(username="hack_user").exists())

    def test_change_password_view(self):
        self.client.force_login(self.admin)
        get_res = self.client.get(reverse("inventory:change_password"))
        self.assertEqual(get_res.status_code, 200)
        post_res = self.client.post(reverse("inventory:change_password"), {
            "old_password": "StrongPass_123!",
            "new_password1": "NewStrongPass_456!",
            "new_password2": "NewStrongPass_456!",
        })
        self.assertEqual(post_res.status_code, 302)

    def test_logout_redirect(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)

    def test_movement_csv_filter(self):
        self.client.force_login(self.admin)
        record_stock_movement(product_id=self.product.pk, movement_type="OUT", quantity=5, user=self.admin)
        res = self.client.get(reverse("inventory:export_csv", args=["movements"]) + "?type=OUT")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"TST-01", res.content)

    def test_profile_settings_redirects_to_profile(self):
        self.client.force_login(self.admin)
        res = self.client.post(reverse("inventory:settings"), {
            "first_name": "Shihab",
            "last_name": "Admin",
            "email": "shihab@example.com",
        })
        self.assertRedirects(res, reverse("inventory:profile"))

    def test_warehouse_crud(self):
        self.client.force_login(self.admin)
        from .models import Warehouse
        # Create
        res = self.client.post(reverse("inventory:warehouse_create"), {
            "code": "WH-TEST", "name": "Test Warehouse", "location": "Test City",
        })
        self.assertEqual(res.status_code, 302)
        wh = Warehouse.objects.get(code="WH-TEST")
        # Edit
        res_edit = self.client.post(reverse("inventory:warehouse_edit", args=[wh.pk]), {
            "code": "WH-TEST", "name": "Updated Warehouse", "location": "New City",
        })
        self.assertEqual(res_edit.status_code, 302)
        wh.refresh_from_db()
        self.assertEqual(wh.name, "Updated Warehouse")
        # Delete
        res_del = self.client.post(reverse("inventory:warehouse_delete", args=[wh.pk]))
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(Warehouse.objects.filter(pk=wh.pk).exists())

    def test_supplier_crud(self):
        self.client.force_login(self.admin)
        from .models import Supplier
        # Create
        res = self.client.post(reverse("inventory:supplier_create"), {
            "name": "Supplier Temp", "email": "temp@example.com", "phone": "123", "address": "Road 1",
        })
        self.assertEqual(res.status_code, 302)
        sup = Supplier.objects.get(name="Supplier Temp")
        # Edit
        res_edit = self.client.post(reverse("inventory:supplier_edit", args=[sup.pk]), {
            "name": "Supplier Updated", "email": "updated@example.com", "phone": "456", "address": "Road 2",
        })
        self.assertEqual(res_edit.status_code, 302)
        sup.refresh_from_db()
        self.assertEqual(sup.name, "Supplier Updated")
        # Delete
        res_del = self.client.post(reverse("inventory:supplier_delete", args=[sup.pk]))
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(Supplier.objects.filter(pk=sup.pk).exists())

    def test_product_delete_or_archive(self):
        self.client.force_login(self.admin)
        # Clean product without history -> deleted permanently
        clean_prod = Product.objects.create(
            sku="CLEAN-01", name="Clean Item", supplier=self.supplier, unit_price="10.00"
        )
        res = self.client.post(reverse("inventory:product_delete", args=[clean_prod.pk]))
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Product.objects.filter(sku="CLEAN-01").exists())

        # Product with movements -> archived
        record_stock_movement(product_id=self.product.pk, movement_type="IN", quantity=10, user=self.admin)
        res_archive = self.client.post(reverse("inventory:product_delete", args=[self.product.pk]))
        self.assertEqual(res_archive.status_code, 302)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_requisition_delete(self):
        self.client.force_login(self.admin)
        req = PurchaseRequisition.objects.create(product=self.product, quantity=5, status="DRAFT")
        res = self.client.post(reverse("inventory:requisition_delete", args=[req.pk]))
        self.assertEqual(res.status_code, 302)
        self.assertFalse(PurchaseRequisition.objects.filter(pk=req.pk).exists())

    def test_product_create_auto_generates_requisition(self):
        self.client.force_login(self.admin)
        res = self.client.post(reverse("inventory:product_create"), {
            "sku": "AUTO-PR-01",
            "name": "Auto Requisition Item",
            "supplier": self.supplier.pk,
            "unit_price": "25.00",
            "reorder_level": 15,
            "target_stock": 60,
            "is_active": "on",
        })
        self.assertEqual(res.status_code, 302)
        prod = Product.objects.get(sku="AUTO-PR-01")
        self.assertEqual(prod.current_stock, 0)
        req = PurchaseRequisition.objects.filter(product=prod, status="DRAFT").first()
        self.assertIsNotNone(req)
        self.assertEqual(req.quantity, 60)

    def test_requisition_create_manual(self):
        self.client.force_login(self.admin)
        prod2 = Product.objects.create(
            sku="MAN-PR-02", name="Manual PR Item", supplier=self.supplier,
            current_stock=20, reorder_level=5, target_stock=50,
        )
        res = self.client.post(reverse("inventory:requisition_create"), {
            "product_id": prod2.pk,
            "quantity": 30,
            "reason": "Special project order",
        })
        self.assertEqual(res.status_code, 302)
        req = PurchaseRequisition.objects.filter(product=prod2).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.quantity, 30)
        self.assertEqual(req.reason, "Special project order")

    def test_requisitions_generate_missing(self):
        self.client.force_login(self.admin)
        prod3 = Product.objects.create(
            sku="SYNC-PR-03", name="Sync Low Stock Item", supplier=self.supplier,
            current_stock=0, reorder_level=10, target_stock=40,
        )
        self.assertFalse(PurchaseRequisition.objects.filter(product=prod3).exists())
        res = self.client.post(reverse("inventory:requisitions_generate_missing"))
        self.assertEqual(res.status_code, 302)
        self.assertTrue(PurchaseRequisition.objects.filter(product=prod3, status="DRAFT").exists())
