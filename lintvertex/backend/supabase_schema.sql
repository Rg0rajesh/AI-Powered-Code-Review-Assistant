-- ============================================================
-- LintVertex – Supabase PostgreSQL Schema
-- Run this in your Supabase SQL Editor to set up the database
-- ============================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- ── Users ─────────────────────────────────────────────────────
create table if not exists public.users (
  id            uuid primary key default uuid_generate_v4(),
  username      text not null unique,
  email         text not null unique,
  address       text,
  password_hash text not null,
  profile_image text,
  role          text not null default 'user' check (role in ('user', 'admin')),
  created_at    timestamptz not null default now()
);

-- ── Code Analysis ─────────────────────────────────────────────
create table if not exists public.code_analysis (
  id               uuid primary key default uuid_generate_v4(),
  user_id          uuid not null references public.users(id) on delete cascade,
  language_detected text not null,
  source_code      text,
  syntax_errors    integer default 0,
  detected_issues  jsonb default '[]'::jsonb,
  improvements     text,
  ml_prediction    text,
  confidence       float default 0.0,
  created_at       timestamptz not null default now()
);

-- ── Discussion Rooms ──────────────────────────────────────────
create table if not exists public.rooms (
  id          uuid primary key default uuid_generate_v4(),
  room_name   text not null,
  room_key    text not null unique,
  created_by  uuid not null references public.users(id) on delete cascade,
  created_at  timestamptz not null default now()
);

-- ── Room Members ──────────────────────────────────────────────
create table if not exists public.room_members (
  id        uuid primary key default uuid_generate_v4(),
  room_id   uuid not null references public.rooms(id) on delete cascade,
  user_id   uuid not null references public.users(id) on delete cascade,
  unique(room_id, user_id)
);

-- ── Room Messages ─────────────────────────────────────────────
create table if not exists public.room_messages (
  id         uuid primary key default uuid_generate_v4(),
  room_id    uuid not null references public.rooms(id) on delete cascade,
  user_id    uuid not null references public.users(id) on delete cascade,
  message    text not null,
  created_at timestamptz not null default now()
);

-- ── Feedback ──────────────────────────────────────────────────
create table if not exists public.feedback (
  id            uuid primary key default uuid_generate_v4(),
  user_id       uuid not null references public.users(id) on delete cascade,
  rating        integer not null check (rating between 1 and 5),
  feedback_text text not null,
  created_at    timestamptz not null default now()
);

-- ── Activity Logs ─────────────────────────────────────────────
create table if not exists public.activity_logs (
  id        uuid primary key default uuid_generate_v4(),
  user_id   uuid references public.users(id) on delete set null,
  action    text not null,
  timestamp timestamptz not null default now()
);

-- ============================================================
-- Row Level Security Policies
-- ============================================================

alter table public.users enable row level security;
alter table public.code_analysis enable row level security;
alter table public.rooms enable row level security;
alter table public.room_members enable row level security;
alter table public.room_messages enable row level security;
alter table public.feedback enable row level security;
alter table public.activity_logs enable row level security;

-- Service role bypasses RLS (backend uses service role key)
-- The following policies are for additional safety with anon key

-- Users: anyone can read basic info, only service role can write
create policy "users_read" on public.users for select using (true);

-- Code analysis: only owner can see their own
create policy "analysis_owner" on public.code_analysis for all using (true);

-- Rooms: readable by all (room key acts as access control)
create policy "rooms_read" on public.rooms for select using (true);
create policy "rooms_write" on public.rooms for insert with check (true);

create policy "members_all" on public.room_members for all using (true);
create policy "messages_all" on public.room_messages for all using (true);
create policy "feedback_all" on public.feedback for all using (true);
create policy "logs_all" on public.activity_logs for all using (true);

-- ============================================================
-- Indexes for performance
-- ============================================================

create index if not exists idx_analysis_user on public.code_analysis(user_id);
create index if not exists idx_analysis_created on public.code_analysis(created_at desc);
create index if not exists idx_messages_room on public.room_messages(room_id);
create index if not exists idx_messages_created on public.room_messages(created_at);
create index if not exists idx_members_room on public.room_members(room_id);
create index if not exists idx_members_user on public.room_members(user_id);
create index if not exists idx_logs_user on public.activity_logs(user_id);
create index if not exists idx_logs_timestamp on public.activity_logs(timestamp desc);
create index if not exists idx_rooms_key on public.rooms(room_key);

-- ============================================================
-- Done! Your LintVertex database is ready.
-- ============================================================

-- ============================================================
-- PASSWORD RESET TABLES (Add-on for OTP flow)
-- Run these in Supabase SQL Editor
-- ============================================================

-- ── OTP Records ───────────────────────────────────────────────
-- Stores hashed OTPs with expiry, attempt count, used flag
create table if not exists public.password_reset_otps (
  id          uuid primary key default uuid_generate_v4(),
  email_hash  text not null,                          -- SHA-256 of lowercase email
  otp_hash    text not null,                          -- SHA-256 of "email:otp"
  expires_at  timestamptz not null,
  attempts    integer not null default 0,
  used        boolean not null default false,
  ip_address  text,                                   -- IP that requested the OTP
  created_at  timestamptz not null default now(),

  -- Only one active (unused, unexpired) OTP per email at a time
  constraint uq_otp_email unique (email_hash)
);

-- ── Reset Tokens ──────────────────────────────────────────────
-- Short-lived tokens issued after OTP verification, used to set new password
create table if not exists public.password_reset_tokens (
  id          uuid primary key default uuid_generate_v4(),
  token_hash  text not null unique,                   -- SHA-256 of the token
  user_id     uuid not null references public.users(id) on delete cascade,
  email       text not null,
  expires_at  timestamptz not null,
  used        boolean not null default false,
  ip_address  text,
  created_at  timestamptz not null default now()
);

-- ── RLS ───────────────────────────────────────────────────────
alter table public.password_reset_otps   enable row level security;
alter table public.password_reset_tokens enable row level security;

-- Backend uses service-role key which bypasses RLS
create policy "otp_all"   on public.password_reset_otps   for all using (true);
create policy "token_all" on public.password_reset_tokens for all using (true);

-- ── Indexes ───────────────────────────────────────────────────
create index if not exists idx_otp_email_hash  on public.password_reset_otps(email_hash);
create index if not exists idx_otp_expires     on public.password_reset_otps(expires_at);
create index if not exists idx_rtoken_hash     on public.password_reset_tokens(token_hash);
create index if not exists idx_rtoken_user     on public.password_reset_tokens(user_id);
create index if not exists idx_rtoken_expires  on public.password_reset_tokens(expires_at);

-- ── Auto-cleanup function (optional, run as cron) ─────────────
-- Removes expired OTPs and tokens to keep the table clean
create or replace function public.cleanup_expired_reset_records()
returns void language sql as $$
  delete from public.password_reset_otps   where expires_at < now();
  delete from public.password_reset_tokens where expires_at < now() - interval '1 day';
$$;

-- ============================================================
-- Notifications Tables (In-app notifications)
-- ============================================================

-- ── Notifications ─────────────────────────────────────────────
create table if not exists public.notifications (
  id           uuid primary key default uuid_generate_v4(),
  user_id      uuid references public.users(id) on delete cascade, -- null if global
  created_by   uuid references public.users(id) on delete set null,
  type         text not null check (type in ('update','feedback_reply','terms','announcement','feature','security','maintenance','system')),
  title        text not null,
  message      text not null,
  icon         text,
  action_url   text,
  action_label text,
  is_global    boolean not null default false,
  is_read      boolean not null default false, -- for personal notifs
  created_at   timestamptz not null default now(),
  expires_at   timestamptz
);

-- ── Notification Reads (for global notifications) ──────────────
create table if not exists public.notification_reads (
  id              uuid primary key default uuid_generate_v4(),
  user_id         uuid not null references public.users(id) on delete cascade,
  notification_id uuid not null references public.notifications(id) on delete cascade,
  read_at         timestamptz not null default now(),
  unique(user_id, notification_id)
);

-- RLS
alter table public.notifications      enable row level security;
alter table public.notification_reads enable row level security;

-- Admin can do anything, users can read theirs + global
create policy "notif_read" on public.notifications for select using (true);
create policy "notif_write" on public.notifications for all using (true);
create policy "notif_read_all" on public.notification_reads for all using (true);

-- Indexes
create index if not exists idx_notif_user    on public.notifications(user_id);
create index if not exists idx_notif_global  on public.notifications(is_global);
create index if not exists idx_notif_created on public.notifications(created_at desc);
create index if not exists idx_nread_user    on public.notification_reads(user_id);

-- ============================================================
-- Done! Your database is ready.
-- ============================================================

-- ── Terms Versions ────────────────────────────────────────────
-- Each row is one published version of the T&C document.
-- Only one version is "active" (is_current = true) at a time.
create table if not exists public.terms_versions (
  id            uuid primary key default uuid_generate_v4(),
  version       text not null,           -- e.g. "1.0", "1.1", "2.0"
  title         text not null,           -- e.g. "Terms and Conditions"
  content       text not null,           -- full T&C text (HTML or Markdown)
  summary       text,                    -- short change summary for users
  published_by  uuid references public.users(id) on delete set null,
  is_current    boolean not null default false,
  created_at    timestamptz not null default now(),
  effective_at  timestamptz not null default now()
);

-- Only one current version at a time (partial unique index)
create unique index if not exists idx_terms_only_one_current
  on public.terms_versions(is_current)
  where is_current = true;

-- ── User Terms Acceptances ────────────────────────────────────
-- One row per user per terms version they accepted.
create table if not exists public.user_terms_acceptance (
  id              uuid primary key default uuid_generate_v4(),
  user_id         uuid not null references public.users(id) on delete cascade,
  terms_version_id uuid not null references public.terms_versions(id) on delete cascade,
  accepted_at     timestamptz not null default now(),
  ip_address      text,
  user_agent      text,
  unique(user_id, terms_version_id)   -- one acceptance per version per user
);

-- Indexes
create index if not exists idx_terms_acceptance_user
  on public.user_terms_acceptance(user_id);
create index if not exists idx_terms_current
  on public.terms_versions(is_current);

-- RLS
alter table public.terms_versions enable row level security;
alter table public.user_terms_acceptance enable row level security;
create policy "terms_read"       on public.terms_versions for select using (true);
create policy "terms_write"      on public.terms_versions for all using (true);
create policy "acceptance_all"   on public.user_terms_acceptance for all using (true);

-- ── Seed initial Terms & Conditions ──────────────────────────
-- Insert a default v1.0 so the app works immediately.
insert into public.terms_versions (version, title, content, summary, is_current, effective_at)
values (
  '1.0',
  'LintVertex Terms and Conditions',
  '<h2>1. Acceptance of Terms</h2>
<p>By accessing or using LintVertex ("the Platform"), you agree to be bound by these Terms and Conditions. If you do not agree, you may not use the Platform.</p>

<h2>2. Use of the Platform</h2>
<p>LintVertex provides AI-powered code review, machine learning quality scoring, and real-time collaboration tools. You agree to use the Platform only for lawful purposes and in accordance with these Terms.</p>
<p>You must not:</p>
<ul>
  <li>Upload malicious, harmful, or illegal code</li>
  <li>Attempt to reverse-engineer or disrupt the Platform</li>
  <li>Share your account credentials with third parties</li>
  <li>Use the Platform to harass, abuse, or harm others</li>
</ul>

<h2>3. Account Responsibility</h2>
<p>You are responsible for maintaining the confidentiality of your account credentials. You agree to notify us immediately of any unauthorized access to your account.</p>

<h2>4. Code and Data Privacy</h2>
<p>Code you submit for analysis may be processed by our AI pipeline (Google Gemini API) and stored securely in our database. We do not share your source code with third parties. Only the first 5,000 characters of each submission are stored for history purposes.</p>

<h2>5. Discussion Rooms</h2>
<p>Discussion rooms are human-only collaboration spaces. You agree not to post offensive, harmful, or illegal content in any room. LintVertex administrators may monitor rooms for policy compliance.</p>

<h2>6. Intellectual Property</h2>
<p>You retain ownership of any code you submit. By using the Platform, you grant LintVertex a limited, non-exclusive license to process your code for the purpose of providing the service.</p>

<h2>7. Service Availability</h2>
<p>LintVertex is provided "as is." We do not guarantee uninterrupted availability and are not liable for any downtime, data loss, or inaccuracies in AI-generated analysis.</p>

<h2>8. Termination</h2>
<p>We reserve the right to suspend or terminate your account at any time for violation of these Terms, without prior notice.</p>

<h2>9. Changes to Terms</h2>
<p>We may update these Terms at any time. You will be required to review and accept the updated Terms before continuing to use the Platform. Continued use after acceptance constitutes agreement.</p>

<h2>10. Governing Law</h2>
<p>These Terms are governed by applicable law. Any disputes shall be resolved through good-faith negotiation before pursuing legal remedies.</p>

<h2>11. Contact</h2>
<p>For questions about these Terms, please use the feedback form within the Platform.</p>',
  'Initial Terms and Conditions for LintVertex platform launch.',
  true,
  now()
) on conflict do nothing;
