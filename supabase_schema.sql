-- Run this in your Supabase project's SQL Editor (Project -> SQL Editor -> New query)
-- to create the tables this agent reads/writes.

create table if not exists orders (
    id text primary key,                 -- Shopify order id/number
    customer_email text not null,
    item text not null,
    total numeric not null,
    final_sale boolean default false,
    fulfilled_at timestamptz,            -- null if not yet shipped
    shipped boolean default false,
    tracking_number text,
    created_at timestamptz default now()
);

create table if not exists inventory (
    product_name text primary key,
    in_stock boolean default true,
    unit_cost numeric not null,
    updated_at timestamptz default now()
);

create table if not exists refund_policy (
    id serial primary key,
    category text not null,              -- refund_request | cancellation | complaint
    condition text not null,             -- e.g. "standard item", "final_sale item"
    window_days int not null,
    max_auto_refund_usd numeric not null,
    notes text
);

create table if not exists email_decisions (
    id serial primary key,
    email_id text not null,
    inbox_source text,
    sender text,
    sender_type text,                    -- customer | supplier | carrier | spam
    category text,
    decision text,                       -- auto_reply | auto_refund | escalate | ignore
    reasoning text,
    source_used text,
    human_response text,
    order_id text,
    created_at timestamptz default now()
);

-- Seed the refund policy table with the same rules as the Excel version,
-- so you can edit them live in Supabase's table editor instead of a file.
insert into refund_policy (category, condition, window_days, max_auto_refund_usd, notes) values
    ('refund_request', 'standard item', 30, 50, 'Full refund if within 30 days and order value under $50'),
    ('refund_request', 'final_sale item', 0, 0, 'No refunds on final sale items - always escalate'),
    ('cancellation', 'not yet shipped', 999, 99999, 'Free cancellation if supplier order not yet placed'),
    ('cancellation', 'already shipped', 0, 0, 'Cannot auto-cancel once shipped - escalate'),
    ('complaint', 'damaged/wrong item', 45, 50, 'Auto-approve replacement if under $50 and photo attached')
on conflict do nothing;

-- Seed a couple of sample orders matching the mock data, so you can test
-- against the same scenarios as run_demo.py once you switch to Supabase.
insert into orders (id, customer_email, item, total, final_sale, fulfilled_at, shipped, tracking_number) values
    ('1001', 'jane@example.com', 'Bluetooth Earbuds', 24.99, false, now() - interval '12 days', true, 'TRK123456'),
    ('1002', 'mike@example.com', 'Smart Watch', 89.00, false, now() - interval '40 days', true, 'TRK987654'),
    ('1003', 'amy@example.com', 'Phone Case', 15.50, false, null, false, null)
on conflict do nothing;

insert into inventory (product_name, in_stock, unit_cost) values
    ('Bluetooth Earbuds', true, 8.50),
    ('Smart Watch', true, 32.00),
    ('Phone Case', true, 2.10)
on conflict do nothing;
