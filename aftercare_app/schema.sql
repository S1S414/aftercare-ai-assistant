BEGIN;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY,
 username TEXT NOT NULL UNIQUE CHECK(length(trim(username)) > 0),
 password_hash TEXT NOT NULL CHECK(length(password_hash) > 0),
 role TEXT NOT NULL CHECK(role IN ('customer','staff')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY,
 order_no TEXT NOT NULL UNIQUE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 product_name TEXT NOT NULL,
 delivery_status TEXT NOT NULL CHECK(delivery_status IN ('in_transit','delivered')),
 expected_delivery_at TEXT NOT NULL,
 delivered_at TEXT,
 created_at TEXT NOT NULL,
 UNIQUE(id,user_id),
 CHECK(expected_delivery_at >= created_at),
 CHECK((delivery_status='in_transit' AND delivered_at IS NULL) OR
       (delivery_status='delivered' AND delivered_at IS NOT NULL AND delivered_at >= created_at))
);
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY,
 order_id INTEGER NOT NULL,
 requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 category TEXT NOT NULL CHECK(category IN ('delivery','product','return_query','other')),
 description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 2000),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_progress','closed')),
 assignee_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,
 resolution TEXT,
 created_at TEXT NOT NULL,
 claimed_at TEXT,
 closed_at TEXT,
 request_key TEXT NOT NULL CHECK(length(trim(request_key)) > 0),
 FOREIGN KEY(order_id,requester_id) REFERENCES orders(id,user_id) ON DELETE RESTRICT,
 UNIQUE(requester_id,request_key),
 CHECK(
  (status='pending' AND assignee_id IS NULL AND claimed_at IS NULL AND closed_at IS NULL AND resolution IS NULL) OR
  (status='in_progress' AND assignee_id IS NOT NULL AND claimed_at IS NOT NULL AND claimed_at >= created_at AND closed_at IS NULL AND resolution IS NULL) OR
  (status='closed' AND assignee_id IS NOT NULL AND claimed_at IS NOT NULL AND closed_at IS NOT NULL AND resolution IS NOT NULL AND length(trim(resolution)) BETWEEN 1 AND 2000 AND claimed_at >= created_at AND closed_at >= claimed_at)
 )
);
CREATE TABLE IF NOT EXISTS ticket_events (
 id INTEGER PRIMARY KEY,
 ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE RESTRICT,
 actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 event_type TEXT NOT NULL CHECK(event_type IN ('created','claimed','closed')),
 from_status TEXT,
 to_status TEXT NOT NULL,
 note TEXT NOT NULL CHECK(length(trim(note)) BETWEEN 1 AND 2000),
 created_at TEXT NOT NULL,
 CHECK(
  (event_type='created' AND from_status IS NULL AND to_status='pending') OR
  (event_type='claimed' AND from_status IS NOT NULL AND from_status='pending' AND to_status='in_progress') OR
  (event_type='closed' AND from_status IS NOT NULL AND from_status='in_progress' AND to_status='closed')
 )
);
CREATE INDEX IF NOT EXISTS idx_orders_owner ON orders(user_id,created_at,id);
CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(requester_id,created_at,id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status,created_at,id);
CREATE INDEX IF NOT EXISTS idx_events_ticket ON ticket_events(ticket_id,id);
CREATE TABLE IF NOT EXISTS assistant_tasks (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 order_id INTEGER NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('delivery','product','return_query','other')),
 description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 2000),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
 state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','completed','cancelled')),
 request_key TEXT NOT NULL UNIQUE,
 ticket_id INTEGER UNIQUE REFERENCES tickets(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(order_id,user_id) REFERENCES orders(id,user_id),
 CHECK((state='completed' AND ticket_id IS NOT NULL) OR (state!='completed' AND ticket_id IS NULL))
);
CREATE TABLE IF NOT EXISTS assistant_events (
 id INTEGER PRIMARY KEY,
 task_id TEXT NOT NULL REFERENCES assistant_tasks(id),
 actor_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL CHECK(action IN ('created','edited','cancelled','completed')),
 version INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assistant_owner ON assistant_tasks(user_id,created_at);
COMMIT;
