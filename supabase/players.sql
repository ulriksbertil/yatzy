-- Kör en gång i Supabase SQL-editorn.
-- Spelarprofiler, koppling till äldre resultat, och en publik bucket för egna bilder.

create table if not exists public.players (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  avatar_key text,
  avatar_url text,
  created_at timestamptz not null default now()
);

create unique index if not exists players_name_lower on public.players (lower(name));

alter table public.scores
  add column if not exists player_id uuid references public.players(id) on delete set null;

create index if not exists scores_player_id on public.scores (player_id);

grant select, insert, update, delete on public.players to anon, authenticated;

alter table public.players enable row level security;

drop policy if exists "players anon all" on public.players;
create policy "players anon all"
  on public.players
  for all
  to anon, authenticated
  using (true)
  with check (true);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'avatars',
  'avatars',
  true,
  2097152,
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
  set public = true,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "avatars public read" on storage.objects;
create policy "avatars public read"
  on storage.objects
  for select
  to public
  using (bucket_id = 'avatars');

drop policy if exists "avatars anon insert" on storage.objects;
create policy "avatars anon insert"
  on storage.objects
  for insert
  to anon, authenticated
  with check (bucket_id = 'avatars');

drop policy if exists "avatars anon update" on storage.objects;
create policy "avatars anon update"
  on storage.objects
  for update
  to anon, authenticated
  using (bucket_id = 'avatars');

drop policy if exists "avatars anon delete" on storage.objects;
create policy "avatars anon delete"
  on storage.objects
  for delete
  to anon, authenticated
  using (bucket_id = 'avatars');
