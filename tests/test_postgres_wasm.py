"""Run emitted migration SQL in ephemeral PostgreSQL-WASM, without a socket.

This validates PostgreSQL syntax/trigger behavior and READ ONLY transaction
semantics, not a native psycopg connection or an external Render deployment.
"""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace


def test_postgres_schema_revocation_triggers_and_readonly_transactions():
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects import postgresql
    from fleetai import db
    from fleetai.auth import _install_assignment_triggers
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    assert node, 'Node is required for isolated PostgreSQL-WASM checks'
    assert (root/'node_modules/@electric-sql/pglite').is_dir(), 'Run npm ci --ignore-scripts for security dev dependencies'
    schema = '\n'.join(str(CreateTable(table).compile(dialect=postgresql.dialect())) + ';'
                       for table in db.Base.metadata.sorted_tables)
    statements = []
    fake = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'), exec_driver_sql=statements.append)
    _install_assignment_triggers(db.Base.metadata, fake)
    harness = r'''
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
const payload = JSON.parse(process.env.FLEETAI_SYNTHETIC_SQL);
const db = new PGlite();
try {
 await db.exec(payload.schema);
 for (const sql of payload.triggers) await db.exec(sql);
 // Trigger installation must be safely repeatable on the isolated schema.
 for (const sql of payload.triggers) await db.exec(sql);
 await db.exec(`INSERT INTO cars(code,driver) VALUES ('PG-1','Alice');
 INSERT INTO driver_telegram_bindings(id,car_code,driver_name,telegram_chat_id) VALUES (1,'PG-1','Alice','123');
 INSERT INTO driver_telegram_links(id,car_code,driver_name,link_token) VALUES (1,'PG-1','Alice','synthetic-link');
 INSERT INTO auth_driver_tickets(token_hash,car_code,driver_name,chat_id,epoch,expires_at) VALUES ('synthetic-ticket','PG-1','Alice','123',0,9999999999);
 INSERT INTO auth_sessions(token_hash,kind,car_code,driver_name,chat_id,epoch,csrf_token,expires_at) VALUES ('synthetic-session','driver','PG-1','Alice','123',0,'synthetic-csrf',9999999999);
 UPDATE cars SET driver='Bob' WHERE code='PG-1';`);
 let rows=(await db.query(`SELECT epoch FROM auth_driver_epochs WHERE car_code='PG-1'`)).rows;
 assert.equal(rows[0].epoch,1);
 assert.equal((await db.query(`SELECT driver FROM cars WHERE code='PG-1'`)).rows[0].driver,'Bob');
 assert.equal((await db.query('SELECT count(*)::integer n FROM driver_telegram_bindings')).rows[0].n,0);
 assert.equal((await db.query('SELECT count(*)::integer n FROM driver_telegram_links')).rows[0].n,0);
 assert.ok((await db.query('SELECT revoked_at FROM auth_sessions')).rows[0].revoked_at);
 assert.ok((await db.query('SELECT revoked_at FROM auth_driver_tickets')).rows[0].revoked_at);
 await db.exec(`UPDATE cars SET driver='Alice' WHERE code='PG-1';`);
 assert.equal((await db.query(`SELECT epoch FROM auth_driver_epochs WHERE car_code='PG-1'`)).rows[0].epoch,2);
 // Rollback must not revoke an otherwise valid assignment transaction.
 await db.exec(`BEGIN; UPDATE cars SET driver='Bob' WHERE code='PG-1'; ROLLBACK;`);
 assert.equal((await db.query(`SELECT epoch FROM auth_driver_epochs WHERE car_code='PG-1'`)).rows[0].epoch,2);
 await db.exec('BEGIN; SET TRANSACTION READ ONLY;');
 assert.equal((await db.query('SELECT count(*)::integer n FROM cars')).rows[0].n,1);
 let blocked=false;
 try { await db.exec(`INSERT INTO cars(code,driver) VALUES ('PG-2','Blocked');`); }
 catch(e) { blocked=e.code==='25006'; }
 assert.ok(blocked,'PostgreSQL must refuse writes in the read-only transaction');
 await db.exec('ROLLBACK;');
 await db.exec(`INSERT INTO cars(code,driver) VALUES ('PG-2','After rollback');`);
 assert.equal((await db.query('SELECT count(*)::integer n FROM cars')).rows[0].n,2);
 await db.exec(`DELETE FROM cars WHERE code='PG-1';`);
 assert.equal((await db.query(`SELECT epoch FROM auth_driver_epochs WHERE car_code='PG-1'`)).rows[0].epoch,3);
 console.log(JSON.stringify({checks:'postgres migration, ABA, rollback, delete revoke, readonly and pool-state boundary',ok:true}));
} finally { await db.close(); }
'''
    import os
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
    env['FLEETAI_SYNTHETIC_SQL'] = json.dumps({'schema':schema,'triggers':statements})
    result = subprocess.run([node, '--input-type=module'], input=harness, text=True,
                            capture_output=True, cwd=root, env=env, timeout=90)
    assert result.returncode == 0, result.stderr[-4000:]
    assert json.loads(result.stdout.splitlines()[-1])['ok'] is True
