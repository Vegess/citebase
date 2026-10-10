-- Citebase: remove test workspaces before going public.
--
-- Run in the Neon console -> SQL Editor, against the production branch.
-- 0. Make a backup first: Neon -> Branches -> Create branch (from main, "now").
-- 1. Put the emails whose WORKSPACES YOU WANT TO KEEP in keep_emails below.
--    Leave it as ('') to delete every workspace.
-- 2. Run PART A alone and read the preview.
-- 3. Run PART B (everything from BEGIN to COMMIT) to delete.
--
-- A workspace is kept if ANY of its members' emails is in keep_emails.

-- ============ PART A: PREVIEW (changes nothing) ============
WITH keep_emails(email) AS (VALUES ('')),
keep_orgs AS (SELECT DISTINCT org_id FROM users WHERE lower(email) IN (SELECT lower(email) FROM keep_emails))
SELECT o.name AS workspace,
       CASE WHEN o.id IN (SELECT org_id FROM keep_orgs) THEN 'KEEP' ELSE 'DELETE' END AS action,
       (SELECT count(*) FROM users u WHERE u.org_id = o.id) AS members,
       (SELECT string_agg(u.email, ', ' ORDER BY u.email) FROM users u WHERE u.org_id = o.id) AS emails,
       (SELECT count(*) FROM documents d WHERE d.org_id = o.id) AS documents
FROM orgs o ORDER BY action, o.name;

-- ============ PART B: DELETE (one transaction) ============
BEGIN;

CREATE TEMP TABLE purge_orgs ON COMMIT DROP AS
  SELECT id FROM orgs WHERE id NOT IN (
    SELECT DISTINCT org_id FROM users
    WHERE lower(email) IN (SELECT lower(e) FROM (VALUES ('')) AS keep_emails(e)));
CREATE TEMP TABLE purge_users ON COMMIT DROP AS
  SELECT id FROM users WHERE org_id IN (SELECT id FROM purge_orgs);
CREATE TEMP TABLE purge_docs ON COMMIT DROP AS
  SELECT id FROM documents WHERE org_id IN (SELECT id FROM purge_orgs);

DELETE FROM verified_answers      WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM conversation_messages WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM conversations         WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM document_events       WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM document_chunks       WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM jobs WHERE (payload::json ->> 'org_id') IN (SELECT id FROM purge_orgs)
                    OR (payload::json ->> 'doc_id') IN (SELECT id FROM purge_docs);
DELETE FROM documents             WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM collection_members    WHERE collection_id IN (SELECT id FROM collections WHERE org_id IN (SELECT id FROM purge_orgs));
DELETE FROM collections           WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM org_invites           WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM audit_events          WHERE org_id IN (SELECT id FROM purge_orgs);
DELETE FROM question_usage        WHERE scope IN (SELECT 'org:' || id FROM purge_orgs)
                                     OR scope IN (SELECT id FROM purge_users);
DELETE FROM user_sessions         WHERE user_id IN (SELECT id FROM purge_users);
DELETE FROM password_resets       WHERE user_id IN (SELECT id FROM purge_users);
DELETE FROM user_identities       WHERE user_id IN (SELECT id FROM purge_users);
DELETE FROM users                 WHERE id IN (SELECT id FROM purge_users);
DELETE FROM orgs                  WHERE id IN (SELECT id FROM purge_orgs);

-- What's left (should be only the workspaces you kept):
SELECT o.name, (SELECT count(*) FROM users u WHERE u.org_id = o.id) AS members FROM orgs o;

COMMIT;
