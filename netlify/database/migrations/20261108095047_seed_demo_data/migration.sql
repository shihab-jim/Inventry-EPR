-- Synthetic demo data (mirrors the original seed_demo command).
INSERT INTO "categories" ("name") VALUES ('Electronics'), ('Apparel'), ('Accessories'), ('Office Supplies');
--> statement-breakpoint
INSERT INTO "suppliers" ("name", "email", "phone") VALUES
  ('Nexa Trading Ltd', 'hello@nexa.example', '01700000001'),
  ('Metro Office Supplies', 'info@metro.example', '01700000002'),
  ('Fashion House Ltd', 'orders@fashion.example', '01700000003');
--> statement-breakpoint
INSERT INTO "warehouses" ("code", "name", "location") VALUES
  ('WH-A', 'Warehouse A', 'Dhaka'),
  ('WH-B', 'Warehouse B', 'Savar'),
  ('WH-C', 'Warehouse C', 'Gazipur'),
  ('WH-D', 'Warehouse D', 'Narayanganj');
--> statement-breakpoint
CREATE TABLE "seed_products" (sku text, name text, category text, supplier text, warehouse text,
  balance int, reorder int, target int, price numeric, issue int, day_offset int);
--> statement-breakpoint
INSERT INTO "seed_products" VALUES
  ('HP-401', 'Wireless Headphones', 'Electronics', 'Nexa Trading Ltd', 'WH-A', 12, 20, 120, 2400.00, 35, 6),
  ('DR-552', 'Women''s Pleated Dress', 'Apparel', 'Fashion House Ltd', 'WH-B', 145, 30, 220, 1750.00, 38, 5),
  ('HB-218', 'Leather Handbag', 'Accessories', 'Fashion House Ltd', 'WH-C', 0, 10, 80, 3200.00, 25, 4),
  ('SW-309', 'Graphic Sweatshirt', 'Apparel', 'Fashion House Ltd', 'WH-D', 75, 40, 150, 1250.00, 45, 6),
  ('KD-114', 'Kids Party Dress', 'Apparel', 'Fashion House Ltd', 'WH-B', 22, 25, 100, 1800.00, 25, 3),
  ('USB-001', 'USB-C Cable', 'Electronics', 'Nexa Trading Ltd', 'WH-A', 18, 20, 75, 250.00, 27, 4),
  ('PAP-001', 'A4 Printer Paper', 'Office Supplies', 'Metro Office Supplies', 'WH-C', 30, 15, 100, 420.00, 35, 5),
  ('INK-001', 'Printer Ink Cartridge', 'Office Supplies', 'Metro Office Supplies', 'WH-C', 12, 5, 30, 1250.00, 8, 2),
  ('SP-801', 'Bluetooth Speaker', 'Electronics', 'Nexa Trading Ltd', 'WH-A', 55, 18, 100, 2900.00, 20, 3),
  ('NB-120', 'Hardcover Notebook', 'Office Supplies', 'Metro Office Supplies', 'WH-D', 220, 60, 300, 180.00, 60, 6);
--> statement-breakpoint
INSERT INTO "products" ("sku", "name", "category_id", "supplier_id", "warehouse_id", "unit_price", "current_stock", "reorder_level", "target_stock")
SELECT s.sku, s.name, c.id, sup.id, w.id, s.price, s.balance, s.reorder, s.target
FROM "seed_products" s
JOIN "categories" c ON c.name = s.category
JOIN "suppliers" sup ON sup.name = s.supplier
JOIN "warehouses" w ON w.code = s.warehouse;
--> statement-breakpoint
INSERT INTO "stock_movements" ("product_id", "movement_type", "quantity", "note", "created_by", "created_at")
SELECT p.id, 'IN', s.balance + s.issue, 'Demo: supplier delivery opening balance', 'system',
       now() - make_interval(days => s.day_offset, hours => 2)
FROM "seed_products" s JOIN "products" p ON p.sku = s.sku;
--> statement-breakpoint
INSERT INTO "stock_movements" ("product_id", "movement_type", "quantity", "note", "created_by", "created_at")
SELECT p.id, 'OUT', s.issue, 'Demo: issued to operations', 'system',
       now() - make_interval(days => greatest(s.day_offset - 2, 0), hours => 1)
FROM "seed_products" s JOIN "products" p ON p.sku = s.sku;
--> statement-breakpoint
INSERT INTO "purchase_requisitions" ("product_id", "quantity", "reason", "created_by", "created_at")
SELECT p.id, p.target_stock - p.current_stock,
       'Auto-generated: stock ' || p.current_stock || ' is at/below reorder level ' || p.reorder_level,
       'system', now() - make_interval(days => greatest(s.day_offset - 2, 0), hours => 1)
FROM "seed_products" s JOIN "products" p ON p.sku = s.sku
WHERE p.current_stock <= p.reorder_level;
--> statement-breakpoint
DROP TABLE "seed_products";
