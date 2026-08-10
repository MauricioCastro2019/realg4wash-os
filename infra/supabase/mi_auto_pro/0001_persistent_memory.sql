-- Mi Auto Pro 0.3 — Persistent Memory
-- Target: dedicated Supabase project when available.
-- Safe for a temporary Supabase branch because everything lives in schema mi_auto_pro.

create schema if not exists mi_auto_pro;

grant usage on schema mi_auto_pro to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Common helpers
-- ---------------------------------------------------------------------------

create or replace function mi_auto_pro.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = mi_auto_pro, public
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Identity / access
-- ---------------------------------------------------------------------------

create table if not exists mi_auto_pro.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  phone text,
  avatar_url text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists mi_auto_pro.providers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  provider_type text not null default 'workshop'
    check (provider_type in ('workshop','carwash','tires','insurance','roadside','dealer','inspection','other')),
  slug text unique,
  phone text,
  email text,
  metadata jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists mi_auto_pro.provider_members (
  provider_id uuid not null references mi_auto_pro.providers(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'staff' check (role in ('owner','admin','advisor','technician','staff')),
  created_at timestamptz not null default timezone('utc', now()),
  primary key (provider_id, user_id)
);

create table if not exists mi_auto_pro.vehicles (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  make text not null,
  model text not null,
  model_year smallint check (model_year between 1900 and 2200),
  trim text,
  alias text,
  vin text,
  plate text,
  color text,
  odometer_km integer check (odometer_km is null or odometer_km >= 0),
  photo_url text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists vehicles_owner_vin_unique
  on mi_auto_pro.vehicles(owner_user_id, upper(vin))
  where vin is not null and btrim(vin) <> '';

create index if not exists vehicles_owner_idx on mi_auto_pro.vehicles(owner_user_id);
create index if not exists vehicles_plate_idx on mi_auto_pro.vehicles(upper(replace(coalesce(plate,''),'-','')));

create table if not exists mi_auto_pro.vehicle_access (
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'viewer' check (role in ('co_owner','manager','viewer')),
  scopes text[] not null default array['history:read']::text[],
  granted_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  revoked_at timestamptz,
  primary key (vehicle_id, user_id)
);

create table if not exists mi_auto_pro.consents (
  id uuid primary key default gen_random_uuid(),
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  provider_id uuid not null references mi_auto_pro.providers(id) on delete cascade,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  scopes text[] not null default array['history:read']::text[],
  status text not null default 'active' check (status in ('active','revoked','expired')),
  granted_at timestamptz not null default timezone('utc', now()),
  expires_at timestamptz,
  revoked_at timestamptz,
  note text,
  created_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists consents_one_active_per_provider_vehicle
  on mi_auto_pro.consents(vehicle_id, provider_id)
  where status = 'active' and revoked_at is null;

create table if not exists mi_auto_pro.provider_invitations (
  id uuid primary key default gen_random_uuid(),
  provider_id uuid not null references mi_auto_pro.providers(id) on delete cascade,
  vehicle_id uuid references mi_auto_pro.vehicles(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete cascade,
  invite_token_hash text not null unique,
  invitee_hint text,
  requested_scopes text[] not null default array['history:read','history:write']::text[],
  status text not null default 'pending' check (status in ('pending','accepted','expired','revoked')),
  expires_at timestamptz not null,
  accepted_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  created_at timestamptz not null default timezone('utc', now())
);

-- ---------------------------------------------------------------------------
-- Memory / provenance
-- ---------------------------------------------------------------------------

create table if not exists mi_auto_pro.import_sessions (
  id uuid primary key default gen_random_uuid(),
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  initiated_by uuid not null references auth.users(id) on delete cascade,
  source_kind text not null check (source_kind in ('whatsapp','pdf','image','invoice','obd','provider_order','manual','mixed')),
  status text not null default 'processing' check (status in ('uploaded','processing','review','committed','failed','cancelled')),
  original_filename text,
  source_count integer not null default 0 check (source_count >= 0),
  candidate_count integer not null default 0 check (candidate_count >= 0),
  committed_count integer not null default 0 check (committed_count >= 0),
  parser_version text,
  summary jsonb not null default '{}'::jsonb,
  error_message text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists mi_auto_pro.source_artifacts (
  id uuid primary key default gen_random_uuid(),
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  import_session_id uuid references mi_auto_pro.import_sessions(id) on delete set null,
  uploaded_by uuid references auth.users(id) on delete set null,
  source_type text not null check (source_type in ('whatsapp','pdf','image','invoice','obd','provider_order','manual','other')),
  source_actor text not null default 'owner' check (source_actor in ('owner','provider','system','third_party')),
  original_filename text,
  mime_type text,
  storage_bucket text,
  storage_path text,
  sha256 text,
  captured_at timestamptz,
  visibility text not null default 'owner' check (visibility in ('owner','shared_provider','vehicle_members')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists source_artifacts_sha_vehicle_unique
  on mi_auto_pro.source_artifacts(vehicle_id, sha256)
  where sha256 is not null;

create table if not exists mi_auto_pro.import_candidates (
  id uuid primary key default gen_random_uuid(),
  import_session_id uuid not null references mi_auto_pro.import_sessions(id) on delete cascade,
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  candidate_type text not null default 'event' check (candidate_type in ('event','issue','odometer','document','merge')),
  status text not null default 'pending' check (status in ('pending','accepted','rejected','merged','needs_review')),
  confidence smallint not null default 0 check (confidence between 0 and 100),
  suggested_payload jsonb not null,
  provenance jsonb not null default '{}'::jsonb,
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists mi_auto_pro.vehicle_events (
  id uuid primary key default gen_random_uuid(),
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  occurred_at timestamptz not null,
  odometer_km integer check (odometer_km is null or odometer_km >= 0),
  category text not null,
  title text not null,
  description text,
  total_cost numeric(12,2) check (total_cost is null or total_cost >= 0),
  currency char(3) not null default 'MXN',
  provider_id uuid references mi_auto_pro.providers(id) on delete set null,
  verification_status text not null default 'ai_candidate'
    check (verification_status in ('ai_candidate','owner_confirmed','provider_confirmed','evidence_verified','disputed')),
  source_confidence smallint check (source_confidence is null or source_confidence between 0 and 100),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists vehicle_events_vehicle_date_idx
  on mi_auto_pro.vehicle_events(vehicle_id, occurred_at desc);
create index if not exists vehicle_events_provider_idx
  on mi_auto_pro.vehicle_events(provider_id) where provider_id is not null;

create table if not exists mi_auto_pro.event_items (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references mi_auto_pro.vehicle_events(id) on delete cascade,
  item_type text not null default 'service' check (item_type in ('part','labor','fluid','service','fee','discount','other')),
  description text not null,
  part_number text,
  quantity numeric(10,3) not null default 1 check (quantity >= 0),
  unit_cost numeric(12,2) check (unit_cost is null or unit_cost >= 0),
  total_cost numeric(12,2) check (total_cost is null or total_cost >= 0),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists mi_auto_pro.vehicle_issues (
  id uuid primary key default gen_random_uuid(),
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  code text,
  system text,
  title text not null,
  description text,
  severity text not null default 'medium' check (severity in ('info','low','medium','high','critical')),
  status text not null default 'open' check (status in ('open','monitoring','resolved','dismissed','disputed')),
  verification_status text not null default 'ai_candidate'
    check (verification_status in ('ai_candidate','owner_confirmed','provider_confirmed','evidence_verified','disputed')),
  first_seen_at timestamptz,
  last_seen_at timestamptz,
  opened_by_event_id uuid references mi_auto_pro.vehicle_events(id) on delete set null,
  resolved_by_event_id uuid references mi_auto_pro.vehicle_events(id) on delete set null,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists vehicle_issues_vehicle_status_idx
  on mi_auto_pro.vehicle_issues(vehicle_id, status);
create index if not exists vehicle_issues_code_idx
  on mi_auto_pro.vehicle_issues(vehicle_id, upper(code)) where code is not null;

create table if not exists mi_auto_pro.event_evidence (
  event_id uuid not null references mi_auto_pro.vehicle_events(id) on delete cascade,
  artifact_id uuid not null references mi_auto_pro.source_artifacts(id) on delete cascade,
  relation_type text not null default 'supports' check (relation_type in ('supports','contradicts','context','invoice','diagnostic','photo')),
  confidence smallint check (confidence is null or confidence between 0 and 100),
  note text,
  created_at timestamptz not null default timezone('utc', now()),
  primary key (event_id, artifact_id)
);

create table if not exists mi_auto_pro.issue_evidence (
  issue_id uuid not null references mi_auto_pro.vehicle_issues(id) on delete cascade,
  artifact_id uuid not null references mi_auto_pro.source_artifacts(id) on delete cascade,
  relation_type text not null default 'supports' check (relation_type in ('supports','contradicts','context','diagnostic','photo')),
  confidence smallint check (confidence is null or confidence between 0 and 100),
  note text,
  created_at timestamptz not null default timezone('utc', now()),
  primary key (issue_id, artifact_id)
);

create table if not exists mi_auto_pro.health_snapshots (
  id uuid primary key default gen_random_uuid(),
  vehicle_id uuid not null references mi_auto_pro.vehicles(id) on delete cascade,
  calculated_at timestamptz not null default timezone('utc', now()),
  overall_score smallint not null check (overall_score between 0 and 100),
  systems jsonb not null default '{}'::jsonb,
  basis_version text not null,
  basis jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists health_snapshots_vehicle_date_idx
  on mi_auto_pro.health_snapshots(vehicle_id, calculated_at desc);

-- Immutable-enough audit trail at application level. Payloads store before/after or action context.
create table if not exists mi_auto_pro.audit_log (
  id bigint generated always as identity primary key,
  vehicle_id uuid references mi_auto_pro.vehicles(id) on delete cascade,
  actor_user_id uuid references auth.users(id) on delete set null,
  actor_provider_id uuid references mi_auto_pro.providers(id) on delete set null,
  entity_type text not null,
  entity_id uuid,
  action text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists audit_log_vehicle_date_idx
  on mi_auto_pro.audit_log(vehicle_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Access helpers. SECURITY DEFINER avoids recursive RLS lookups.
-- ---------------------------------------------------------------------------

create or replace function mi_auto_pro.is_vehicle_owner(p_vehicle_id uuid)
returns boolean
language sql
stable
security definer
set search_path = mi_auto_pro, public, auth
as $$
  select exists (
    select 1
    from mi_auto_pro.vehicles v
    where v.id = p_vehicle_id
      and v.owner_user_id = auth.uid()
  );
$$;

create or replace function mi_auto_pro.is_provider_member(p_provider_id uuid)
returns boolean
language sql
stable
security definer
set search_path = mi_auto_pro, public, auth
as $$
  select exists (
    select 1
    from mi_auto_pro.provider_members pm
    where pm.provider_id = p_provider_id
      and pm.user_id = auth.uid()
  );
$$;

create or replace function mi_auto_pro.has_vehicle_scope(p_vehicle_id uuid, p_scope text)
returns boolean
language sql
stable
security definer
set search_path = mi_auto_pro, public, auth
as $$
  select
    mi_auto_pro.is_vehicle_owner(p_vehicle_id)
    or exists (
      select 1
      from mi_auto_pro.vehicle_access va
      where va.vehicle_id = p_vehicle_id
        and va.user_id = auth.uid()
        and va.revoked_at is null
        and (p_scope = any(va.scopes) or 'vehicle:manage' = any(va.scopes))
    )
    or exists (
      select 1
      from mi_auto_pro.consents c
      join mi_auto_pro.provider_members pm on pm.provider_id = c.provider_id
      where c.vehicle_id = p_vehicle_id
        and pm.user_id = auth.uid()
        and c.status = 'active'
        and c.revoked_at is null
        and (c.expires_at is null or c.expires_at > timezone('utc', now()))
        and (p_scope = any(c.scopes) or 'vehicle:manage' = any(c.scopes))
    );
$$;

revoke all on function mi_auto_pro.is_vehicle_owner(uuid) from public;
revoke all on function mi_auto_pro.is_provider_member(uuid) from public;
revoke all on function mi_auto_pro.has_vehicle_scope(uuid,text) from public;
grant execute on function mi_auto_pro.is_vehicle_owner(uuid) to authenticated, service_role;
grant execute on function mi_auto_pro.is_provider_member(uuid) to authenticated, service_role;
grant execute on function mi_auto_pro.has_vehicle_scope(uuid,text) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Updated-at triggers
-- ---------------------------------------------------------------------------

drop trigger if exists profiles_set_updated_at on mi_auto_pro.profiles;
create trigger profiles_set_updated_at before update on mi_auto_pro.profiles
for each row execute function mi_auto_pro.set_updated_at();

drop trigger if exists providers_set_updated_at on mi_auto_pro.providers;
create trigger providers_set_updated_at before update on mi_auto_pro.providers
for each row execute function mi_auto_pro.set_updated_at();

drop trigger if exists vehicles_set_updated_at on mi_auto_pro.vehicles;
create trigger vehicles_set_updated_at before update on mi_auto_pro.vehicles
for each row execute function mi_auto_pro.set_updated_at();

drop trigger if exists import_sessions_set_updated_at on mi_auto_pro.import_sessions;
create trigger import_sessions_set_updated_at before update on mi_auto_pro.import_sessions
for each row execute function mi_auto_pro.set_updated_at();

drop trigger if exists vehicle_events_set_updated_at on mi_auto_pro.vehicle_events;
create trigger vehicle_events_set_updated_at before update on mi_auto_pro.vehicle_events
for each row execute function mi_auto_pro.set_updated_at();

drop trigger if exists vehicle_issues_set_updated_at on mi_auto_pro.vehicle_issues;
create trigger vehicle_issues_set_updated_at before update on mi_auto_pro.vehicle_issues
for each row execute function mi_auto_pro.set_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table mi_auto_pro.profiles enable row level security;
alter table mi_auto_pro.providers enable row level security;
alter table mi_auto_pro.provider_members enable row level security;
alter table mi_auto_pro.vehicles enable row level security;
alter table mi_auto_pro.vehicle_access enable row level security;
alter table mi_auto_pro.consents enable row level security;
alter table mi_auto_pro.provider_invitations enable row level security;
alter table mi_auto_pro.import_sessions enable row level security;
alter table mi_auto_pro.source_artifacts enable row level security;
alter table mi_auto_pro.import_candidates enable row level security;
alter table mi_auto_pro.vehicle_events enable row level security;
alter table mi_auto_pro.event_items enable row level security;
alter table mi_auto_pro.vehicle_issues enable row level security;
alter table mi_auto_pro.event_evidence enable row level security;
alter table mi_auto_pro.issue_evidence enable row level security;
alter table mi_auto_pro.health_snapshots enable row level security;
alter table mi_auto_pro.audit_log enable row level security;

-- Profiles
create policy profiles_select_self on mi_auto_pro.profiles for select to authenticated
  using (id = auth.uid());
create policy profiles_insert_self on mi_auto_pro.profiles for insert to authenticated
  with check (id = auth.uid());
create policy profiles_update_self on mi_auto_pro.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

-- Providers / membership
create policy providers_select_member on mi_auto_pro.providers for select to authenticated
  using (mi_auto_pro.is_provider_member(id));
create policy providers_insert_authenticated on mi_auto_pro.providers for insert to authenticated
  with check (created_by = auth.uid());
create policy providers_update_member on mi_auto_pro.providers for update to authenticated
  using (mi_auto_pro.is_provider_member(id));

create policy provider_members_select_self_or_peer on mi_auto_pro.provider_members for select to authenticated
  using (user_id = auth.uid() or mi_auto_pro.is_provider_member(provider_id));
create policy provider_members_insert_member on mi_auto_pro.provider_members for insert to authenticated
  with check (user_id = auth.uid() or mi_auto_pro.is_provider_member(provider_id));

-- Vehicles
create policy vehicles_select_access on mi_auto_pro.vehicles for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(id, 'history:read'));
create policy vehicles_insert_owner on mi_auto_pro.vehicles for insert to authenticated
  with check (owner_user_id = auth.uid());
create policy vehicles_update_owner on mi_auto_pro.vehicles for update to authenticated
  using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());
create policy vehicles_delete_owner on mi_auto_pro.vehicles for delete to authenticated
  using (owner_user_id = auth.uid());

-- Vehicle member access is controlled by the owner.
create policy vehicle_access_select_related on mi_auto_pro.vehicle_access for select to authenticated
  using (user_id = auth.uid() or mi_auto_pro.is_vehicle_owner(vehicle_id));
create policy vehicle_access_insert_owner on mi_auto_pro.vehicle_access for insert to authenticated
  with check (mi_auto_pro.is_vehicle_owner(vehicle_id) and granted_by = auth.uid());
create policy vehicle_access_update_owner on mi_auto_pro.vehicle_access for update to authenticated
  using (mi_auto_pro.is_vehicle_owner(vehicle_id));
create policy vehicle_access_delete_owner on mi_auto_pro.vehicle_access for delete to authenticated
  using (mi_auto_pro.is_vehicle_owner(vehicle_id));

-- Consent belongs to the owner; provider members may read consent granted to them.
create policy consents_select_related on mi_auto_pro.consents for select to authenticated
  using (owner_user_id = auth.uid() or mi_auto_pro.is_provider_member(provider_id));
create policy consents_insert_owner on mi_auto_pro.consents for insert to authenticated
  with check (owner_user_id = auth.uid() and mi_auto_pro.is_vehicle_owner(vehicle_id));
create policy consents_update_owner on mi_auto_pro.consents for update to authenticated
  using (owner_user_id = auth.uid() and mi_auto_pro.is_vehicle_owner(vehicle_id));

create policy invitations_select_provider on mi_auto_pro.provider_invitations for select to authenticated
  using (mi_auto_pro.is_provider_member(provider_id) or accepted_by = auth.uid());
create policy invitations_insert_provider on mi_auto_pro.provider_invitations for insert to authenticated
  with check (created_by = auth.uid() and mi_auto_pro.is_provider_member(provider_id));
create policy invitations_update_provider on mi_auto_pro.provider_invitations for update to authenticated
  using (mi_auto_pro.is_provider_member(provider_id) or accepted_by = auth.uid());

-- Shared vehicle-memory tables.
create policy import_sessions_select_access on mi_auto_pro.import_sessions for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:read'));
create policy import_sessions_insert_write on mi_auto_pro.import_sessions for insert to authenticated
  with check (initiated_by = auth.uid() and mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));
create policy import_sessions_update_write on mi_auto_pro.import_sessions for update to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

create policy artifacts_select_access on mi_auto_pro.source_artifacts for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:read'));
create policy artifacts_insert_write on mi_auto_pro.source_artifacts for insert to authenticated
  with check (uploaded_by = auth.uid() and mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

create policy candidates_select_access on mi_auto_pro.import_candidates for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:read'));
create policy candidates_insert_write on mi_auto_pro.import_candidates for insert to authenticated
  with check (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));
create policy candidates_update_write on mi_auto_pro.import_candidates for update to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

create policy events_select_access on mi_auto_pro.vehicle_events for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:read'));
create policy events_insert_write on mi_auto_pro.vehicle_events for insert to authenticated
  with check (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));
create policy events_update_write on mi_auto_pro.vehicle_events for update to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

create policy event_items_select_access on mi_auto_pro.event_items for select to authenticated
  using (exists (select 1 from mi_auto_pro.vehicle_events e where e.id = event_id and mi_auto_pro.has_vehicle_scope(e.vehicle_id, 'history:read')));
create policy event_items_insert_write on mi_auto_pro.event_items for insert to authenticated
  with check (exists (select 1 from mi_auto_pro.vehicle_events e where e.id = event_id and mi_auto_pro.has_vehicle_scope(e.vehicle_id, 'history:write')));
create policy event_items_update_write on mi_auto_pro.event_items for update to authenticated
  using (exists (select 1 from mi_auto_pro.vehicle_events e where e.id = event_id and mi_auto_pro.has_vehicle_scope(e.vehicle_id, 'history:write')));

create policy issues_select_access on mi_auto_pro.vehicle_issues for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:read'));
create policy issues_insert_write on mi_auto_pro.vehicle_issues for insert to authenticated
  with check (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));
create policy issues_update_write on mi_auto_pro.vehicle_issues for update to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

create policy event_evidence_select_access on mi_auto_pro.event_evidence for select to authenticated
  using (exists (select 1 from mi_auto_pro.vehicle_events e where e.id = event_id and mi_auto_pro.has_vehicle_scope(e.vehicle_id, 'history:read')));
create policy event_evidence_insert_write on mi_auto_pro.event_evidence for insert to authenticated
  with check (exists (select 1 from mi_auto_pro.vehicle_events e where e.id = event_id and mi_auto_pro.has_vehicle_scope(e.vehicle_id, 'history:write')));

create policy issue_evidence_select_access on mi_auto_pro.issue_evidence for select to authenticated
  using (exists (select 1 from mi_auto_pro.vehicle_issues i where i.id = issue_id and mi_auto_pro.has_vehicle_scope(i.vehicle_id, 'history:read')));
create policy issue_evidence_insert_write on mi_auto_pro.issue_evidence for insert to authenticated
  with check (exists (select 1 from mi_auto_pro.vehicle_issues i where i.id = issue_id and mi_auto_pro.has_vehicle_scope(i.vehicle_id, 'history:write')));

create policy health_select_access on mi_auto_pro.health_snapshots for select to authenticated
  using (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:read'));
create policy health_insert_write on mi_auto_pro.health_snapshots for insert to authenticated
  with check (mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

create policy audit_select_owner on mi_auto_pro.audit_log for select to authenticated
  using (vehicle_id is null or mi_auto_pro.is_vehicle_owner(vehicle_id));
create policy audit_insert_related on mi_auto_pro.audit_log for insert to authenticated
  with check ((vehicle_id is null and actor_user_id = auth.uid()) or mi_auto_pro.has_vehicle_scope(vehicle_id, 'history:write'));

-- ---------------------------------------------------------------------------
-- Grants (RLS still applies to authenticated users)
-- ---------------------------------------------------------------------------

grant select, insert, update, delete on all tables in schema mi_auto_pro to authenticated;
grant all privileges on all tables in schema mi_auto_pro to service_role;
grant usage, select on all sequences in schema mi_auto_pro to authenticated, service_role;

-- Future tables in this schema inherit sensible API grants.
alter default privileges in schema mi_auto_pro grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema mi_auto_pro grant all privileges on tables to service_role;
alter default privileges in schema mi_auto_pro grant usage, select on sequences to authenticated, service_role;
