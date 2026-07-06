# TerminusDB API Notes (v12.0.6)

Empirically verified against a local `terminusdb/terminusdb-server:v12.0.6` instance
(running on port 6363, admin password `root`).  All tests used throwaway databases.

---

## 1. Schema push with `full_replace`

- **Endpoint**: `POST /api/document/{org}/{db}?graph_type=schema&full_replace=true`
- **@context required**: YES.  Omitting it yields 400 `api:NoContextFoundInSchema`.
- **Idempotent**: re-pushing the identical schema returns 200 with the list of class/enum
  `@id` values.  No duplicate classes, no data loss.
- **Payload**: the composed schema JSON array (including the `@context` object as the
  first element).

---

## 2. Validation timing (when existing data violates new schema)

- **Push-time validation**: TerminusDB validates the full database against the new schema
  at push time.  If ANY existing instance document violates the new schema, the push
  **fails immediately** with 400 `api:SchemaCheckFailure`.
- **Error examples**:
  - Dropping an enum value that is in use → `instance_not_of_class` witness.
  - Adding a required field without a default → `instance_not_cardinality_one` witness.
- **Conclusion**: **Schema-first with validation-at-push** works.  You do NOT need
  a separate migrations-first phase — TerminusDB will reject a schema that breaks
  existing data.  The `lms-schema apply` command can push schema first and get a clear
  go/no-go signal.

---

## 3. Lexical key syntax

- **Accepted**: `{"@id": "X", "@type": "Class", "@key": {"@type": "Lexical", "@fields": ["name"]}, ...}`
  pushes successfully.
- **@id generation**: inserting `{"@type": "SchemaModule", "name": "test-module", ...}`
  produces `@id = "SchemaModule/test-module"` (a **URI-encoding of the key field value**).
- **Duplicate key insert**: POST with the same key value → 400 `api:DocumentIdAlreadyExists`.
  This is a **conflict**, not a silent upsert.
- **UPSERT recipe**: Two options tested working:
  1. **PUT** with `@id` set to the deterministic key-based IRI, with `graph_type=instance`.
  2. **POST** with `full_replace=true` and `graph_type=instance` (replaces ALL instances
     matching the type, so use carefully for single-type collections).

---

## 4. Branching

- **Create branch**: `POST /api/branch/{org}/{db}/local/branch/{new}` with body
  `{"origin": "main"}`. Returns 200 `api:BranchResponse`.  Duplicate → 400
  `api:BranchExistsError`.
- **Schema push on branch**: `POST /api/document/{org}/{db}/local/branch/{b}?graph_type=schema&full_replace=true`
  — works.
- **Instance writes on branch**: the existing `insert_documents` / `replace_document`
  methods (which use `_doc_path(branch)`) work unchanged.
- **Branch copies data**: creating a branch from main copies both schema AND instance data.
  Verified: after creating feature from main, reading instances on feature returns the
  same documents as main.
- **Auto-create on write**: writing to a non-existent branch implicitly creates it (200).
- **Delete branch**: `DELETE /api/branch/{org}/{db}/local/branch/{b}` → 200.
- **List branches**: `GET /api/branch/{org}/{db}` → 405 (not supported in v12).

---

## 5. Promote (merge) mechanism

- **`POST /api/reset/{org}/{db}/local/branch/{target}`** with
  `{"commit_descriptor": "{org}/{db}/local/commit/<identifier>"}` **reliably works**
  for moving one branch pointer to any other commit — schema AND instance changes
  are transferred.
- **`POST /api/apply/{org}/{db}`** with `before_commit`, `after_commit`, `commit_info`,
  and `type: "Squash"` where commit refs are **bare identifiers** (not full paths) also
  returns 200.
- **`POST /api/rebase/{org}/{db}/local/branch/{b}`** with `{"author": "...",
  "rebase_from": "{org}/{db}/local/branch/main"}` rebases. Returns 200.
- **Recommendation for `promote`**: use `reset_branch` (the reset endpoint). It is
  the simplest, most reliable mechanism observed; it moves the target branch pointer
  to exactly the source commit, carrying both schema and instance changes.  No
  separate endpoint for instance vs. schema is needed.
- **No apply endpoint works with branch-path references** (`local/branch/main`).
  Must use bare commit identifiers (the `identifier` field from `/api/log`).

---

## 6. Branch head retrieval

- **Endpoint**: `GET /api/log/{org}/{db}/local/branch/{branch}`
- Returns a JSON array of commits, newest first.
- The first entry's `identifier` field is the branch head commit identifier.
- Use as commit descriptor: `{org}/{db}/local/commit/{identifier}`.
- Also works without `?count=N` — returns all commits; first entry is always the head.

## 7. Branch-scoped GraphQL

- **Path form**: `POST /api/graphql/{org}/{db}/local/branch/{branch}` with the standard
  GraphQL JSON body (`{"query": "..."}`).
- **✅ Working**: `/api/graphql/admin/db/local/branch/feature` returns branch-scoped
  data (only documents committed on that branch).
- **❌ Not working**: `/api/graphql/admin/db/branch/feature` (returns 403 "Bad descriptor
  path").  Query parameter `?branch=...` is silently ignored.
- **Default (no branch in path)**: returns main-branch data.

---

## 8. GraphQL smoke test query shape

- **Working query**: `POST /api/graphql/{org}/{db}/local/branch/{branch}`
  ```json
  {"query": "{ ClassName(limit:1) { _id } }"}
  ```
- Returns `{"data": {"ClassName": [...]}}` on success.
- Works for every concrete (non-abstract) class, even if no instances exist.
- Abstract classes return `"Cannot query field"` error — this is expected; skip them.
