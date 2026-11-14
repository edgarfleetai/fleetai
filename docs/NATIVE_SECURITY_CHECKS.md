# Opt-in native PostgreSQL security checks

This is a separate, destructive **synthetic-only** audit, not an application server
or a connection tool for an existing database. It is deliberately outside `tests/`:
`native_cases.py` is not a default pytest filename, fixtures are an explicitly
loaded plugin (not `conftest.py`), and the supervisor supplies its own pytest
configuration, root and `--confcutdir`. The SQLite test fixtures cannot intercept it.
Do not invoke the cases directly or add them to the default test suite.

## Prerequisites and invocation

Use an existing isolated Python environment with the repository requirements,
pytest, requests and psycopg 3 already installed. Nothing is downloaded or installed
by the harness. Supply existing native `initdb`, `pg_ctl` and `postgres` executables;
PostgreSQL 17.11 / psycopg 3.2.13 were used by the predecessor scratch audit.
The supervisor uses the **same Python executable** that launches it.

Freeze all intended source changes on the authorized feature branch before the
run; the supervisor never commits untested code. By default it requires a clean
worktree at the exact commit/branch. For a pre-commit acceptance run, explicitly
pass `--source-manifest /absolute/path/outside-git/frozen.json`: its `commit`,
`branch`, exact `status` (`git status --porcelain -z`) and `files` mapping
(relative paths to SHA-256 for all tracked plus nonignored untracked files) must
match before execution. The same complete inventory, status, branch and HEAD
must remain unchanged afterward, including new-file additions/removals. This
permits a frozen uncommitted security fix to be tested before approval/commit;
it does not relax cluster, role, synthetic-data or transport guards.
The supervisor does not commit, push, mount/unmount disk images or deploy.

Example from the repository root, using the previously downloaded official
Postgres.app image after the parent operator mounts it at the existing mountpoint:

```sh
SOURCE_COMMIT="$(git rev-parse HEAD)" # record this at source freeze
.venv-security/bin/python -B security_checks/native/run_native.py \
  --postgres-bin "$HOME/.hermes/profiles/fleetai/cache/scratch/pg-dist/mount/Postgres.app/Contents/Versions/17/bin" \
  --artifacts-dir "$HOME/.hermes/profiles/fleetai/cache/scratch/npg-final" \
  --expected-commit "$SOURCE_COMMIT" \
  --expected-branch security/hermes-finance-readonly-20261106 \
  --allow-native-postgres \
  --synthetic-data-only
```

Both safety flags and all four value arguments are required. Choose a **new**
artifacts path for every attempt; it must not already exist, must be outside all
Git working trees, and must be short enough for a Unix-domain socket (the
supervisor validates this before initdb). The example's directory is private,
not a Git artifact. Run as an ordinary user, never root. No supplied DSN, existing
cluster or inherited application/PG credentials are accepted.

## Isolation and lifecycle

* A fresh `initdb` cluster lives only in the private artifacts runtime directory.
  The supervisor creates random passwords and SCRAM login roles; host authentication
  is `reject`, `listen_addresses=''`, and the only socket directory is mode 0700.
* The database owner/writer and observer/admin are separate from the finance
  reader. PUBLIC database permissions, including TEMP, are revoked. The reader
  receives CONNECT, schema USAGE and SELECT on only five finance tables: `cars`,
  `driver_debts`, `driver_debt_payments`, `driver_wallet_transactions`, `operations`.
  No privilege or role inheritance is granted.
* The worker receives an allowlisted environment, not the operator's application
  secrets, PG variables, proxies, pytest options or plugin configuration. The
  supervisor also clears inherited PG variables before using libpq itself.
* psycopg synchronous entry points validate the exact Unix socket, port,
  synthetic database and synthetic roles. Async connections are rejected.
  SQLAlchemy's connection event independently enforces PostgreSQL/psycopg and
  the worker datasource. Python socket audit hooks reject other connections,
  DNS and Internet datagrams. Requests calls and worker subprocess execution
  are forbidden; attempted transports fail the audit even if application code
  catches the error. Direct SQLite connections are forbidden in the worker.
* The real factory runs with `TESTING=False`, real migrations and assignment
  triggers, psycopg and real QueuePool engines. **Only** built-in sample fleet
  seeding is temporarily replaced; no auth, routing, migration, rent accrual,
  payment or contract business logic is replaced.
* On ordinary failure, timeout, SIGINT, SIGTERM or SIGHUP, the supervisor kills
  the worker process group if needed, stops PostgreSQL (`fast`, then `immediate`
  fallback), removes plaintext password files and removes the whole runtime
  directory after shutdown. It does not detach a caller-owned distribution.
  A shutdown failure returns nonzero and leaves the private cluster for manual
  recovery, but removes plaintext configuration/passwords and raw JUnit output.

These are defense-in-depth guards for the inspected Python application, **not an
OS sandbox** against malicious C extensions, direct libpq/FFI calls, or arbitrary
filesystem access. No program can guarantee cleanup after SIGKILL, power loss,
or OS/filesystem failure. Keep the runtime private; if forcibly interrupted,
stop the cluster with its supplied `pg_ctl -D ARTIFACTS/r/data -m immediate -w stop`
and remove `ARTIFACTS/r` before treating cleanup as verified. Do not run alongside
source edits or against production resources.

## Coverage and evidence

The predecessor had 39 cases (38 passed; one incorrect POST status expectation).
The durable suite retains all coverage, splits that compound case into three,
and adds two atomic trim-alias uniqueness cases, for **43 cases**:

* actual `pg_stat_activity` + `pg_blocking_pids` lock waits in both orderings,
  session expiry during a wait, ABA trigger revocation and rollback;
* serialization-before-commit, snapshot rollback, pool reuse, ticket/enrollment
  CAS rollback and concurrent single-winner behavior;
* INSERT/UPDATE/DELETE denied independently on each of the five finance tables,
  no CREATE/TEMP, no inherited privilege or auth-table reads;
* all five finance endpoint variants via GET/HEAD/OPTIONS, SELECT-only identity,
  server read-only transactions and complete database snapshots proving no writes;
* POST rejection accepts **only 403 or 405**, spies on the real registered finance
  handler to prove it was not invoked, and compares complete before/after database
  snapshots. No positive access expectation was relaxed;
* missing read-only datasource is an independent fail-closed 503 case, with no
  inherited datasource fallback and a complete unchanged database snapshot.

A successful run requires exit 0, exactly 43 executed cases with no skips, five
observed real PostgreSQL lock waits, unchanged tracked source, verified cluster
shutdown and deleted runtime/password files. Artifacts are mode-private:

* `run-metadata.json`: versions, commit/branch, tracked source hashes, test counts,
  observer digest and cleanup results;
* `native.xml`: testcase names, counts and redacted failures/errors, never raw SQL
  exception details, credentials, stdout or stderr;
* `lock-observer.json`: synthetic backend PIDs, wait type and blocking PIDs observed
  directly from PostgreSQL (not inferred from thread timing).

The durable promotion is syntax-checked only until the parent freezes source and
runs it. Prior scratch results do not establish that the promoted harness passes.
