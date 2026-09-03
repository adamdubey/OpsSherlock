CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  sku TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  total_cents INTEGER NOT NULL CHECK (total_cents > 0),
  authorization_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
