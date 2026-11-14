"""Explicit opt-in supervisor: disposable native PostgreSQL, never a supplied DSN."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', required=True, type=Path)
    parser.add_argument('--artifacts-dir', required=True, type=Path)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--expected-branch', required=True)
    parser.add_argument('--source-manifest', type=Path,
        help='Explicit frozen working-tree inventory outside Git; allows testing before committing')
    parser.add_argument('--allow-native-postgres', action='store_true')
    parser.add_argument('--synthetic-data-only', action='store_true')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Assertions must be enabled; do not use python -O or PYTHONOPTIMIZE')
    if not (args.allow_native_postgres and args.synthetic_data_only):
        parser.error('Both safety acknowledgements are required')
    if not re.fullmatch(r'[0-9a-f]{40}', args.expected_commit):
        parser.error('--expected-commit must be a complete lowercase SHA-1')
    if os.geteuid() == 0:
        parser.error('Do not run initdb as root')
    os.umask(0o077)
    # libpq itself reads this process environment, not subprocess env=.
    for key in tuple(os.environ):
        if key.startswith('PG'):
            del os.environ[key]
    binaries = args.postgres_bin.resolve(strict=True)
    for name in ('initdb', 'pg_ctl', 'postgres'):
        if not (binaries / name).is_file() or not os.access(binaries / name, os.X_OK):
            parser.error('Missing executable: ' + name)
    artifacts = args.artifacts_dir.resolve()
    if artifacts.is_relative_to(ROOT) or any((p / '.git').exists() for p in (artifacts, *artifacts.parents)):
        parser.error('Artifacts must be outside Git working trees')
    # Never reuse a directory containing another run, credentials, or live cluster.
    if artifacts.exists():
        parser.error('Artifacts directory must not exist; choose a fresh private path')
    artifacts.mkdir(mode=0o700, parents=True)
    runtime = artifacts / 'r'
    runtime.mkdir(mode=0o700)
    socket_dir = runtime / 's'
    socket_dir.mkdir(mode=0o700)
    if len(os.fsencode(str(socket_dir / '.s.PGSQL.65535'))) >= 104:
        shutil.rmtree(runtime)
        parser.error('Artifacts path too long for a portable Unix socket; choose a shorter path')
    data = runtime / 'data'
    private = runtime / 'connection-private.json'
    password_file = runtime / 'init-password'
    config = {'admin': 'audit_bootstrap', 'admin_password': secrets.token_urlsafe(32),
              'writer': 'audit_writer', 'writer_password': secrets.token_urlsafe(32),
              'reader': 'audit_reader', 'reader_password': secrets.token_urlsafe(32),
              'database': 'fleetai_native_synthetic', 'socket_dir': str(socket_dir),
              'data_dir': str(data), 'port': 49000 + secrets.randbelow(15000)}
    env = {'PATH': os.defpath, 'HOME': str(runtime), 'TMPDIR': str(runtime),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONUTF8': '1',
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONPATH': os.pathsep.join((str(HERE), str(ROOT))),
           'FLEETAI_NATIVE_PRIVATE_CONFIG': str(private), 'FLEETAI_NATIVE_OPT_IN': 'synthetic-only'}
    stage = 'preflight'
    metadata = {'only_unix_socket': True, 'synthetic_data_only': True,
                'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    result_code = 2
    worker = None
    hashes = {}
    initial_status = None

    def command(argv, timeout=60):
        result = subprocess.run([str(x) for x in argv], env=env, cwd=ROOT,
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError('Command failed (output suppressed to protect credentials)')
        return result.stdout

    def source_inventory():
        names = command(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).split('\0')
        result = {}
        for name in filter(None, names):
            path = ROOT / name
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise RuntimeError('Source inventory must not follow external links')
            if path.is_file():
                result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def on_signal(signum, frame):
        raise SystemExit(128 + signum)

    previous = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        if command(['git', 'rev-parse', 'HEAD']).strip() != args.expected_commit:
            raise RuntimeError('Unexpected source commit')
        if command(['git', 'branch', '--show-current']).strip() != args.expected_branch:
            raise RuntimeError('Unexpected source branch')
        initial_status = command(['git', 'status', '--porcelain', '-z'])
        hashes = source_inventory()
        if args.source_manifest:
            manifest_path = args.source_manifest.resolve(strict=True)
            if manifest_path.is_relative_to(ROOT):
                raise RuntimeError('Frozen manifest must be outside the source tree')
            frozen = json.loads(manifest_path.read_text())
            if (frozen.get('commit') != args.expected_commit or frozen.get('branch') != args.expected_branch
                    or frozen.get('status') != initial_status or frozen.get('files') != hashes):
                raise RuntimeError('Working tree does not match the explicit frozen manifest')
            metadata['source_freeze_mode'] = 'explicit_worktree_manifest'
        elif initial_status:
            raise RuntimeError('Dirty source requires an explicit frozen manifest; never commit untested code')
        else:
            metadata['source_freeze_mode'] = 'clean_commit'
        metadata['checked_commit'] = args.expected_commit
        metadata['checked_branch'] = args.expected_branch
        for path, content in ((password_file, config['admin_password'] + '\n'), (private, json.dumps(config))):
            with path.open('x', encoding='utf-8') as stream:
                stream.write(content)
        stage = 'initdb'
        command([binaries / 'initdb', '-D', data, '-U', config['admin'], '--pwfile=' + str(password_file),
                 '--auth-local=scram-sha-256', '--auth-host=reject', '--encoding=UTF8', '--locale=C',
                 '--no-instructions'], 120)
        password_file.unlink()
        stage = 'start'
        # pg_ctl parses this string itself. Quote paths even when they contain spaces.
        import shlex
        options = ("-c listen_addresses='' -k " + shlex.quote(str(socket_dir)) + ' -p ' + str(config['port'])
                   + ' -c unix_socket_permissions=0700 -c max_connections=40'
                   + ' -c password_encryption=scram-sha-256 -c log_statement=none'
                   + ' -c log_min_error_statement=panic -c log_min_messages=panic')
        command([binaries / 'pg_ctl', '-D', data, '-l', runtime / 'postgres.log', '-o', options, '-w', 'start'])
        stage = 'roles-and-database'
        from isolation import install
        install(config)
        import psycopg
        from psycopg import sql
        common = dict(host=str(socket_dir), port=config['port'], user=config['admin'],
                      password=config['admin_password'], connect_timeout=5)
        with psycopg.connect(dbname='postgres', autocommit=True, **common) as connection:
            assert connection.execute('SHOW data_directory').fetchone()[0] == str(data)
            assert connection.execute('SHOW listen_addresses').fetchone()[0] == ''
            assert connection.execute('SHOW password_encryption').fetchone()[0] == 'scram-sha-256'
            metadata['postgres_version'] = connection.execute('SELECT version()').fetchone()[0]
            metadata['psycopg_version'] = psycopg.__version__
            for role, password in ((config['writer'], config['writer_password']), (config['reader'], config['reader_password'])):
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role), sql.Literal(password)))
            connection.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(config['database']), sql.Identifier(config['writer'])))
            connection.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(config['database'])))
            connection.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(config['database']), sql.Identifier(config['writer']), sql.Identifier(config['reader'])))
        with psycopg.connect(dbname=config['database'], **common) as connection:
            connection.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
            connection.execute(sql.SQL('GRANT USAGE,CREATE ON SCHEMA public TO {}').format(sql.Identifier(config['writer'])))
        stage = 'native-tests'
        worker = subprocess.Popen([sys.executable, '-B', '-m', 'pytest', '-c', str(HERE / 'pytest.ini'), '-p', 'native_fixtures',
            '-p', 'no:cacheprovider', '--confcutdir=' + str(HERE), '--rootdir=' + str(HERE),
            '-o', 'addopts=', '--basetemp=' + str(runtime / 'pytest'), str(HERE / 'native_cases.py'),
            '-q', '--tb=no', '--show-capture=no', '--junitxml=' + str(runtime / 'native-raw.xml')],
            env=env, cwd=runtime, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        # Never emit pytest stdout/stderr or tracebacks: failures can expose DSNs.
        worker.communicate(timeout=420)
        result_code = worker.returncode
        raw_report = runtime / 'native-raw.xml'
        report = artifacts / 'native.xml'
        if raw_report.exists():
            tree = ET.parse(raw_report)
            cases = list(tree.iter('testcase'))
            metadata['counts'] = {'tests': len(cases),
                **{key: sum(len(case.findall(tag)) for case in cases)
                   for key, tag in [('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]}}
            # Preserve names/counts only; SQLAlchemy failures may contain secrets.
            for case in cases:
                for node in list(case):
                    if node.tag in ('failure', 'error', 'system-out', 'system-err'):
                        node.attrib.clear()
                        node.text = 'Details suppressed by native supervisor; reproduce only in synthetic cluster.'
            tree.write(report, encoding='utf-8', xml_declaration=True)
            metadata['junit_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
            if len(cases) != 43 or metadata['counts']['skipped']:
                raise RuntimeError('Native collection must exercise exactly 43 cases without skips')
        else:
            raise RuntimeError('No native test evidence produced')
        observer = artifacts / 'lock-observer.json'
        if observer.exists():
            observed = json.loads(observer.read_text())
            metadata['observed_lock_waits'] = len(observed)
            metadata['lock_observer_sha256'] = hashlib.sha256(observer.read_bytes()).hexdigest()
            if result_code == 0 and (len(observed) != 5 or any(
                    row['wait_event_type'] != 'Lock' or row['expected_blocker_pid'] not in row['blocking_pids']
                    for row in observed)):
                raise RuntimeError('Incomplete PostgreSQL lock observer evidence')
        elif result_code == 0:
            raise RuntimeError('Missing PostgreSQL lock observer evidence')
    except BaseException as error:
        metadata['blocked_stage'] = stage
        metadata['error_type'] = type(error).__name__
        result_code = error.code if isinstance(error, SystemExit) and isinstance(error.code, int) else 2
    finally:
        # Complete cleanup even when a second termination signal arrives.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        cleanup_errors = []
        if worker is not None and worker.poll() is None:
            try:
                os.killpg(worker.pid, signal.SIGTERM)
                try:
                    worker.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGKILL)
                    worker.communicate(timeout=10)
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_errors.append(type(error).__name__)
        metadata['cluster_stopped'] = not (data / 'postmaster.pid').exists()
        if not metadata['cluster_stopped']:
            for mode in ('fast', 'immediate'):
                try:
                    command([binaries / 'pg_ctl', '-D', data, '-m', mode, '-w', 'stop'], 60)
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    pass
                if not (data / 'postmaster.pid').exists():
                    metadata['cluster_stopped'] = True
                    break
        # Remove plaintext passwords even when shutdown fails; leave data only for recovery.
        for path in (private, password_file, runtime / 'native-raw.xml'):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                cleanup_errors.append(type(error).__name__)
        metadata['password_files_removed'] = not private.exists() and not password_file.exists()
        try:
            metadata['source_freeze_preserved'] = (
                command(['git', 'rev-parse', 'HEAD']).strip() == args.expected_commit
                and command(['git', 'branch', '--show-current']).strip() == args.expected_branch
                and initial_status is not None
                and command(['git', 'status', '--porcelain', '-z']) == initial_status
                and source_inventory() == hashes)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            metadata['source_freeze_preserved'] = False
        if not metadata['source_freeze_preserved']:
            result_code = 3
        if hashes:
            try:
                metadata['tracked_files_unchanged'] = all((ROOT / name).is_file() and
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
            except OSError:
                metadata['tracked_files_unchanged'] = False
            metadata['tracked_file_hashes'] = hashes
            if not metadata['tracked_files_unchanged']:
                result_code = 3
        if metadata['cluster_stopped']:
            try:
                shutil.rmtree(runtime)
            except OSError as error:
                cleanup_errors.append(type(error).__name__)
        else:
            result_code = 3
        metadata['runtime_removed'] = not runtime.exists()
        metadata['cleanup_errors'] = cleanup_errors
        if cleanup_errors or not metadata['runtime_removed'] or not metadata['password_files_removed']:
            result_code = 3
        metadata['exit_code'] = result_code
        (artifacts / 'run-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print(json.dumps({k: v for k, v in metadata.items() if k != 'tracked_file_hashes'}), flush=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return result_code


if __name__ == '__main__':
    sys.exit(main())
