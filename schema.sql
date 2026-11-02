-- =====================================================================
-- Transport Accounting — Supabase / PostgreSQL schema
-- Run this ONCE in Supabase: SQL Editor -> New query -> paste -> Run
-- =====================================================================

-- ---------- Settings ----------
create table if not exists settings (
    key   text primary key,
    value text not null
);

insert into settings (key, value) values
    ('company_name',                 'My Transport'),
    ('default_commission_type',      'FIXED'),      -- FIXED (Rs per trip) or PERCENT (of truck hire)
    ('default_commission_value',     '0'),
    ('freight_basis',                'LOADED'),     -- LOADED or UNLOADED weight
    ('require_gr_for_truck_balance', 'false'),      -- GR No. must be filled before truck balance payment
    ('pod_upload_marks_received',    'true'),       -- uploading a POD copy ticks "POD received"
    ('drive_root_folder_name',       'Transport Docs')
on conflict (key) do nothing;

-- ---------- Accounts (Cash, Bank, Party, Truck Owner, Pump, Income, Expense) ----------
-- opening_balance: positive = Debit (receivable / asset), negative = Credit (payable)
create table if not exists accounts (
    id              bigserial primary key,
    name            text not null,
    acc_type        text not null,
    mobile          text,
    address         text,
    gstin           text,
    pan             text,
    bank_details    text,
    account_no      text,
    location        text,
    opening_balance numeric(14,2) not null default 0,
    system_code     text unique,
    active          boolean not null default true,
    created_at      timestamptz not null default now(),
    unique (acc_type, name)
);

alter table accounts drop constraint if exists accounts_acc_type_check;
alter table accounts add constraint accounts_acc_type_check
    check (acc_type in ('CASH','BANK','PARTY','OWNER','PUMP','INCOME','EXPENSE','OTHER'));

insert into accounts (name, acc_type, system_code) values
    ('Cash',              'CASH',    'CASH'),
    ('Advance Adjustment','OTHER',   'ADV_ADJ'),
    ('Freight Income',    'INCOME',  'FREIGHT_INCOME'),
    ('Lorry Hire',        'EXPENSE', 'LORRY_HIRE'),
    ('Commission Income', 'INCOME',  'COMMISSION_INCOME'),
    ('Shortage Expense',  'EXPENSE', 'SHORTAGE_EXP'),
    ('Shortage Recovery', 'INCOME',  'SHORTAGE_REC'),
    ('Demurrage Paid',    'EXPENSE', 'DEMURRAGE_EXP'),
    ('Demurrage Charged', 'INCOME',  'DEMURRAGE_INC')
on conflict (system_code) do nothing;

-- ---------- Trucks ----------
create table if not exists trucks (
    id            bigserial primary key,
    truck_no      text not null unique,          -- stored uppercase without spaces
    owner_id      bigint not null references accounts(id),
    driver_name   text,
    driver_mobile text,
    active        boolean not null default true,
    created_at    timestamptz not null default now()
);

-- ---------- Places / Materials (dropdown lists) ----------
create table if not exists lookups (
    id   bigserial primary key,
    kind text not null check (kind in ('PLACE','MATERIAL')),
    name text not null,
    unique (kind, name)
);

-- ---------- Trips ----------
create table if not exists trips (
    id                 bigserial primary key,
    trip_no            text generated always as (
                           'T-' || case when id < 10000 then lpad(id::text, 4, '0') else id::text end
                       ) stored unique,
    booking_date       date not null default current_date,
    party_id           bigint not null references accounts(id),
    from_place         text,                               -- optional
    to_place           text not null,
    material           text,
    party_rate         numeric(12,2) not null default 0,   -- Rs per ton
    approx_weight      numeric(12,3),
    truck_id           bigint references trucks(id),
    owner_id           bigint references accounts(id),     -- owner at time of assignment
    truck_rate         numeric(12,2),                      -- Rs per ton
    loaded_weight      numeric(12,3),
    loading_date       date,
    unloaded_weight    numeric(12,3),
    unloading_date     date,
    pod_received       boolean not null default false,
    pod_date           date,
    gr_no              text,
    gr_date            date,
    freight_basis      text not null default 'LOADED' check (freight_basis in ('LOADED','UNLOADED')),
    commission_type    text not null default 'FIXED'  check (commission_type in ('FIXED','PERCENT')),
    commission_value   numeric(12,2) not null default 0,
    party_shortage_amt numeric(12,2) not null default 0,
    truck_shortage_amt numeric(12,2) not null default 0,
    remarks            text,
    is_cancelled       boolean not null default false,
    cancel_reason      text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

-- (for a database made with an earlier version)
alter table trips alter column from_place drop not null;
alter table trips add column if not exists truck_demurrage_amt numeric(12,2) not null default 0;
alter table trips add column if not exists party_demurrage_amt numeric(12,2) not null default 0;
alter table trips add column if not exists demurrage_days      integer;
-- POD handed over to the party (bill submission)
alter table trips add column if not exists pod_submitted   boolean not null default false;
alter table trips add column if not exists pod_submit_date date;
alter table trips add column if not exists pod_submit_mode text;      -- Hand / Courier / Email / WhatsApp
alter table trips add column if not exists pod_submit_ref  text;      -- courier docket / person name
alter table trips add column if not exists party_demurrage_days integer;

create unique index if not exists trips_gr_unique
    on trips (upper(gr_no)) where gr_no is not null and is_cancelled = false;
create index if not exists trips_booking_date on trips (booking_date);
create index if not exists trips_party on trips (party_id);
create index if not exists trips_owner on trips (owner_id);

-- ---------- Vouchers + double-entry lines ----------
-- v_type:  TRIP (auto, from trip freight/hire/commission/shortage)
--          RECEIPT (party money in), PAYMENT (truck money out), DIESEL (pump -> truck)
--          PUMP_PAYMENT, CONTRA (cash <-> bank), OTHER (expense / misc)
create table if not exists vouchers (
    id            bigserial primary key,
    v_date        date not null,
    v_type        text not null check (v_type in
                      ('TRIP','RECEIPT','PAYMENT','DIESEL','PUMP_PAYMENT','CONTRA','OTHER')),
    purpose       text,          -- ADVANCE / BALANCE / ON_ACCOUNT / ...
    trip_id       bigint references trips(id),
    amount        numeric(14,2) not null check (amount >= 0),
    litres        numeric(10,2),
    rate          numeric(10,2),
    ref_no        text,
    narration     text,
    is_cancelled  boolean not null default false,
    cancel_reason text,
    cancelled_at  timestamptz,
    created_at    timestamptz not null default now()
);
-- one bank credit split over many trucks shares one batch_no (bank book shows it as one line)
alter table vouchers add column if not exists batch_no text;

create index if not exists vouchers_trip on vouchers (trip_id);
create index if not exists vouchers_batch on vouchers (batch_no);
create index if not exists vouchers_date on vouchers (v_date);

create table if not exists ledger_entries (
    id         bigserial primary key,
    voucher_id bigint not null references vouchers(id) on delete cascade,
    account_id bigint not null references accounts(id),
    debit      numeric(14,2) not null default 0,
    credit     numeric(14,2) not null default 0,
    check (debit >= 0 and credit >= 0 and (debit = 0 or credit = 0))
);
create index if not exists ledger_account on ledger_entries (account_id);
create index if not exists ledger_voucher on ledger_entries (voucher_id);

-- Active (not cancelled) ledger lines with voucher + trip details
create or replace view v_ledger as
select e.id, e.voucher_id, e.account_id, e.debit, e.credit,
       v.v_date, v.v_type, v.purpose, v.trip_id, v.ref_no, v.narration, v.litres, v.rate,
       t.trip_no, t.gr_no, v.batch_no
from ledger_entries e
join vouchers v on v.id = e.voucher_id
left join trips t on t.id = v.trip_id
where v.is_cancelled = false;

-- ---------- Trip documents (files live in Google Drive) ----------
create table if not exists trip_documents (
    id            bigserial primary key,
    trip_id       bigint not null references trips(id),
    doc_type      text not null check (doc_type in ('GR','POD','OTHER')),
    file_name     text not null,
    mime_type     text,
    size_bytes    bigint,
    drive_file_id text not null,
    drive_link    text,
    uploaded_by   text,
    uploaded_at   timestamptz not null default now(),
    is_deleted    boolean not null default false,
    delete_reason text
);
create index if not exists trip_documents_trip on trip_documents (trip_id);

-- Edit history: every trip edit / cancel and every entry created or cancelled
create table if not exists audit_log (
    id        bigserial primary key,
    at        timestamptz not null default now(),
    username  text,
    entity    text not null,          -- trip / voucher
    entity_id bigint,
    action    text not null,          -- create / edit / cancel
    details   jsonb
);
create index if not exists audit_entity on audit_log (entity, entity_id);

-- Drive folder id cache (path like "2026/11-Nov/T-0001")
create table if not exists drive_folders (
    path      text primary key,
    folder_id text not null
);
