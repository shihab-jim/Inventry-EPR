import { sql } from "drizzle-orm";
import {
  boolean, check, integer, numeric, pgTable, serial, text, timestamp, uniqueIndex,
} from "drizzle-orm/pg-core";

export const categories = pgTable("categories", {
  id: serial().primaryKey(),
  name: text().notNull().unique(),
});

export const suppliers = pgTable("suppliers", {
  id: serial().primaryKey(),
  name: text().notNull().unique(),
  email: text().notNull().default(""),
  phone: text().notNull().default(""),
  address: text().notNull().default(""),
});

export const warehouses = pgTable("warehouses", {
  id: serial().primaryKey(),
  code: text().notNull().unique(),
  name: text().notNull(),
  location: text().notNull().default(""),
});

export const products = pgTable(
  "products",
  {
    id: serial().primaryKey(),
    sku: text().notNull().unique(),
    name: text().notNull(),
    categoryId: integer("category_id").references(() => categories.id, { onDelete: "set null" }),
    supplierId: integer("supplier_id").references(() => suppliers.id, { onDelete: "set null" }),
    warehouseId: integer("warehouse_id").references(() => warehouses.id, { onDelete: "set null" }),
    unitPrice: numeric("unit_price", { precision: 12, scale: 2 }).notNull().default("0"),
    currentStock: integer("current_stock").notNull().default(0),
    reorderLevel: integer("reorder_level").notNull().default(10),
    targetStock: integer("target_stock").notNull().default(50),
    isActive: boolean("is_active").notNull().default(true),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    check("products_stock_non_negative", sql`${t.currentStock} >= 0`),
    check("products_target_above_reorder", sql`${t.targetStock} > ${t.reorderLevel}`),
    check("products_price_non_negative", sql`${t.unitPrice} >= 0`),
  ],
);

export const stockMovements = pgTable("stock_movements", {
  id: serial().primaryKey(),
  productId: integer("product_id").notNull().references(() => products.id, { onDelete: "restrict" }),
  movementType: text("movement_type", { enum: ["IN", "OUT"] }).notNull(),
  quantity: integer().notNull(),
  note: text().notNull().default(""),
  createdBy: text("created_by").notNull().default(""),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const requisitions = pgTable(
  "purchase_requisitions",
  {
    id: serial().primaryKey(),
    productId: integer("product_id").notNull().references(() => products.id, { onDelete: "restrict" }),
    quantity: integer().notNull(),
    status: text({ enum: ["DRAFT", "APPROVED", "ORDERED", "REJECTED", "FULFILLED"] }).notNull().default("DRAFT"),
    reason: text().notNull().default("Automatic low-stock reorder"),
    createdBy: text("created_by").notNull().default(""),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    uniqueIndex("one_open_requisition_per_product")
      .on(t.productId)
      .where(sql`status in ('DRAFT', 'APPROVED', 'ORDERED')`),
  ],
);

export const purchaseOrders = pgTable("purchase_orders", {
  id: serial().primaryKey(),
  requisitionId: integer("requisition_id").notNull().unique().references(() => requisitions.id, { onDelete: "restrict" }),
  supplierId: integer("supplier_id").notNull().references(() => suppliers.id, { onDelete: "restrict" }),
  quantity: integer().notNull(),
  unitCost: numeric("unit_cost", { precision: 12, scale: 2 }).notNull(),
  status: text({ enum: ["ORDERED", "RECEIVED"] }).notNull().default("ORDERED"),
  createdBy: text("created_by").notNull().default(""),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  receivedBy: text("received_by").notNull().default(""),
  receivedAt: timestamp("received_at", { withTimezone: true }),
});

/** Tracks Identity sign-ups so the first account can be made the administrator. */
export const appUsers = pgTable("app_users", {
  id: text().primaryKey(),
  email: text().notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
