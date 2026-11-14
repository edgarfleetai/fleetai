"""Fail-closed Python transport guards for the synthetic native audit.

Defense in depth, not an OS sandbox against deliberately hostile native code.
Install before importing the application; never use with a real datasource.
"""
import os
from pathlib import Path
import socket
import sys


def install(config, *, worker=False):
    import psycopg

    socket_dir = str(Path(config['socket_dir']).resolve())
    expected_socket = str(Path(socket_dir) / ('.s.PGSQL.' + str(config['port'])))
    attempts = []

    def deny():
        attempts.append(True)
        raise RuntimeError('Transport outside the synthetic audit cluster is forbidden')

    def audit(event, args):
        if event == 'socket.connect':
            sock, address = args
            if sock.family != socket.AF_UNIX or os.fsdecode(address) != expected_socket:
                deny()
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'):
            deny()
        if event in ('socket.sendto', 'socket.sendmsg') and args[0].family != socket.AF_UNIX:
            deny()
        if worker and event == 'sqlite3.connect':
            deny()
        if worker and event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.fork'):
            deny()

    sys.addaudithook(audit)
    original = psycopg.Connection.connect

    def guarded(cls, conninfo='', **kwargs):
        options = psycopg.conninfo.conninfo_to_dict(conninfo)
        options.update(kwargs)
        # Explicit values only: no environment/service/default fallback or hostaddr.
        allowed = {'host', 'port', 'dbname', 'user', 'password', 'connect_timeout',
                   'application_name', 'autocommit', 'row_factory', 'cursor_factory',
                   'prepare_threshold', 'context'}
        if (set(options) - allowed or options.get('host') != socket_dir
                or str(options.get('port')) != str(config['port'])
                or options.get('dbname') not in (config['database'], 'postgres')
                or options.get('user') not in (config['admin'], config['writer'], config['reader'])
                or (options.get('dbname') == 'postgres' and options.get('user') != config['admin'])):
            deny()
        return original(conninfo, **kwargs)

    psycopg.Connection.connect = classmethod(guarded)
    psycopg.connect = psycopg.Connection.connect

    async def no_async(*args, **kwargs):
        deny()

    psycopg.AsyncConnection.connect = classmethod(no_async)
    if worker:
        import requests

        def no_request(*args, **kwargs):
            deny()

        requests.sessions.Session.request = no_request
    return attempts
