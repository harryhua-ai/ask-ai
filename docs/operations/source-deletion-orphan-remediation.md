# Source deletion orphan inventory and bounded remediation

This runbook covers historical residue created before Issue #174. It does not
authorize production mutation. Merging the source fix does not delete old
orphans, reopen Issue #121, satisfy its remediation acknowledgement, deploy a
release, or make Issue #138 GO.

## Read-only inventory

Start from an explicitly reviewed source ID. Do not infer ownership from a
filename, a shared prefix, customer text, or the absence of a `data_sources`
row. Record the target environment, database identity, timestamp, source ID,
and command output before drawing a conclusion.

Use strict source boundaries in PostgreSQL; `%` and `_` in a source ID are
literal characters, not patterns:

```sql
-- Bind :source_id; all statements are SELECT-only.
SELECT count(*) AS documents
FROM documents
WHERE left(source_id, length(:source_id) + 1) = :source_id || '/';

SELECT count(*) AS versions
FROM document_versions
WHERE left(source_id, length(:source_id) + 1) = :source_id || '/';

SELECT count(*) AS version_chunks
FROM document_version_chunks c
JOIN document_versions v ON v.id = c.version_id
WHERE left(v.source_id, length(:source_id) + 1) = :source_id || '/';

SELECT id, ordinal, status, doc_count, chunk_count,
       ready_at, activated_at, retired_at, purged_at
FROM index_generations
WHERE source_id = :source_id
ORDER BY ordinal;
```

Vector inventory must reuse the existing read-only iterator boundary
`source_id.startswith(source_id + "/")`. Never use a Weaviate TEXT
`equal`/`like` filter as deletion evidence or as a delete primitive. For an
upload source, inspect only the exact direct child
`data/uploads/data-sources/<source_id>` after independently verifying that the
source was `filesystem + upload_mode=true` and that its persisted `root_path`
was exactly that application-owned path. Do not follow symlinks or inspect
file contents merely to reconstruct an inventory.

## Future bounded repair gate

A separate production change request must approve any repair. Its reviewed
manifest must enumerate exact source IDs and expected counts per layer, and a
dry run must prove all of the following before apply is available:

1. the environment and database are the intended production target;
2. source ownership is independently established, even when the config row is
   already absent;
3. Weaviate candidates are actual UUIDs found by a strict source-boundary scan;
4. upload targets are direct, non-symlink children of the authoritative shared
   upload root, with literal-prefix siblings listed as protected controls;
5. PostgreSQL versions/chunks/generations are linked only to the reviewed
   source identity, including old and ghost generations;
6. backups, rollback limits, maintenance window, operator, and post-apply
   zero-residue queries are recorded.

Apply must be one source at a time and stop on any mismatch, partial vector
receipt, readback residue, filesystem permission error, path ambiguity, or DB
transaction failure. It must preserve a durable retry/audit anchor until every
required layer verifies zero. Never widen the manifest by prefix, run a global
GC as a substitute, delete ordinary filesystem/git/model/shared storage, or
claim backup erasure. Backups and audit-retention policy remain separate.

## Main risks

- Historical config loss can make upload ownership unprovable; that is a
  fail-closed result, not permission to guess.
- Filesystem deletion is not transactionally reversible with PostgreSQL or
  Weaviate. Partial apply therefore requires a retained retry anchor and an
  explicit operator-visible failure state.
- A stale or incomplete generation view can leave reconstructable chunk text.
- A textual prefix, symlink, mount change, or wrong working directory can cross
  source boundaries.
- Code acceptance, production remediation, release approval, deployment, and
  rollback safety are separate gates with separate evidence.
