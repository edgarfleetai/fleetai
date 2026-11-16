"""Dashboard change history, tasks and the AI assistant (Claude is faked)."""
import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from sqlalchemy import create_engine, text

from test_dashboard_v4 import BASE, csrf_headers, fin_dash, login, op_change  # noqa: F401  (fixture)


def make_app(url, **extra):
    from dashboard.app import create_app
    cfg = {'TESTING': True, 'SECRET_KEY': 'x' * 40, 'DATABASE_URL': url, 'PUBLIC_URL': BASE,
           'WIALON_FETCH': lambda: ([], None)}
    cfg.update(extra)
    return create_app(cfg)


def test_dashboard_writes_are_logged_in_history(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    h = csrf_headers(c)
    pv = c.post('/api/v4/ops/preview', base_url=BASE, json={'message': '897 получил 12000'}, headers=h).get_json()
    assert c.post('/api/v4/ops/commit', base_url=BASE, headers=h, json={
        'message': '897 получил 12000', 'fingerprint': pv['fingerprint'], 'key': 'hist-key-000000001'}).status_code == 200
    assert op_change(c, h, 2, 'delete', {}, 'hist-del-00000001').status_code == 200
    ev = c.get('/api/v4/history?days=5', base_url=BASE).get_json()['events']
    texts = [e['summary'] for e in ev]
    assert any('Записано: 897 получил 12000' in t for t in texts)
    assert any(t.startswith('Удалена операция #2 621 2000') for t in texts)
    assert all(e['source'] == 'dashboard' and e['actor'] == 'owner' for e in ev)
    assert [e['car'] for e in c.get('/api/v4/history?car=621', base_url=BASE).get_json()['events']] == ['621']


def test_snapshot_catches_changes_made_outside(fin_dash):
    from dashboard import history
    eng = create_engine(fin_dash.engine_url)
    t0 = datetime.now()
    assert history.snapshot_and_compare(eng, eng, now=t0) == []          # first snapshot is the baseline
    with eng.begin() as conn:                                            # the bot / old site changes things
        conn.execute(text("UPDATE cars SET driver = 'Пётр' WHERE code = '897'"))
        conn.execute(text("UPDATE operations SET amount = 2500 WHERE id = 2"))
        conn.execute(text("DELETE FROM operations WHERE id = 1"))
    assert history.snapshot_and_compare(eng, eng, now=t0 + timedelta(minutes=10)) is None   # at most hourly
    found = history.snapshot_and_compare(eng, eng, now=t0 + timedelta(hours=2))
    texts = [s for _, _, s in found]
    assert '897: водитель «Иван» → «Пётр»' in texts
    assert any(t.startswith('Изменена операция #2') and '2500' in t for t in texts)
    assert any(t.startswith('Удалена операция #1') for t in texts)
    ev = history.events(eng, days=1, now=t0 + timedelta(hours=2))
    assert {e['source'] for e in ev} == {'outside'} and len(ev) == 3


def test_snapshot_skips_changes_made_in_dashboard(fin_dash):
    from dashboard import history
    eng = create_engine(fin_dash.engine_url)
    t0 = datetime.now()
    history.snapshot_and_compare(eng, eng, now=t0)
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    h = csrf_headers(c)
    assert op_change(c, h, 2, 'delete', {}, 'hist-del-00000002').status_code == 200
    assert history.snapshot_and_compare(eng, eng, now=t0 + timedelta(hours=2)) == []


def test_tasks_crud_needs_csrf(fin_dash):
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    assert c.post('/api/v4/tasks', base_url=BASE, json={'data': {'title': 'x'}}).status_code == 403
    h = csrf_headers(c)
    r = c.post('/api/v4/tasks', base_url=BASE, headers=h,
               json={'data': {'title': 'Сделать ТО', 'car_code': '621', 'due_date': '2026-12-01'}})
    tid = r.get_json()['id']
    again = c.post('/api/v4/tasks', base_url=BASE, headers=h, json={'data': {'title': 'Сделать ТО', 'car_code': '621'}})
    assert again.get_json()['id'] == tid                                    # no duplicate
    assert c.post('/api/v4/tasks', base_url=BASE, headers=h,
                  json={'data': {'title': 'Срок', 'due_date': '01.12'}}).status_code == 400
    assert c.post(f'/api/v4/tasks/{tid}/done', base_url=BASE, headers=h, json={}).status_code == 200
    assert c.get('/api/v4/tasks', base_url=BASE).get_json()['tasks'][0]['status'] == 'done'
    assert c.post(f'/api/v4/tasks/{tid}/delete', base_url=BASE, headers=h, json={}).status_code == 200
    assert c.get('/api/v4/tasks', base_url=BASE).get_json()['tasks'] == []
    texts = [e['summary'] for e in c.get('/api/v4/history', base_url=BASE).get_json()['events']]
    assert 'Новая задача: Сделать ТО' in texts and 'Выполнена задача: Сделать ТО' in texts


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kw):
        self.calls.append(dict(copy.copy(kw), messages=list(kw['messages'])))
        return self.script.pop(0)


def fake_client(script):
    m = FakeMessages(script)
    return (lambda: NS(beta=NS(messages=m))), m


def tool(i, name, inp):
    return NS(type='tool_use', id=i, name=name, input=inp)


def test_assistant_reads_sets_tasks_and_only_proposes_money(fin_dash, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    factory, messages = fake_client([
        NS(stop_reason='tool_use', usage=None, content=[
            NS(type='text', text='Смотрю.'),
            tool('t1', 'finance', {'car': '621'}),
            tool('t2', 'create_task', {'title': 'Позвонить водителю 621', 'car_code': '621'}),
            tool('t3', 'propose_operation', {'message': '621 получил 5000'}),
            tool('t4', 'nonexistent', {})]),
        NS(stop_reason='end_turn', usage=None, content=[NS(type='text', text='**Готово**: задача поставлена.')]),
    ])
    c = make_app(fin_dash.engine_url, ASSISTANT_CLIENT=factory, ASSISTANT_SYNC=True).test_client()
    assert c.post('/api/v4/assistant', base_url=BASE, json={'message': 'привет'}).status_code == 401
    login(c)
    assert c.post('/api/v4/assistant', base_url=BASE, json={'message': 'привет'}).status_code == 403   # no CSRF
    eng = create_engine(fin_dash.engine_url)
    count = lambda: eng.connect().execute(text("SELECT count(*) FROM operations")).scalar()
    ops_before = count()
    r = c.post('/api/v4/assistant', base_url=BASE, headers=csrf_headers(c), json={'message': 'Что по 621?'})
    assert r.status_code == 200, r.get_json()
    job = c.get('/api/v4/assistant/job/' + r.get_json()['job'], base_url=BASE).get_json()
    assert job['status'] == 'done' and job['reply'].startswith('**Готово**')
    assert job['tools'] == ['finance', 'create_task', 'propose_operation', 'nonexistent']
    assert job['proposals'][0]['message'] == '621 получил 5000' and job['proposals'][0]['items'][0]['amount'] == 5000
    assert count() == ops_before                                         # money is never written by the assistant
    tasks = c.get('/api/v4/tasks', base_url=BASE).get_json()['tasks']
    assert [(t['title'], t['source'], t['car']) for t in tasks] == [('Позвонить водителю 621', 'assistant', '621')]
    first, second = messages.calls
    assert first['model'] == 'claude-opus-5-5' and 'tool_choice' not in first and first['fallbacks'] == 'default'
    assert 'Что по 621?' in first['messages'][0]['content'] and '[Сейчас' in first['messages'][0]['content']
    results = {x['tool_use_id']: x for x in second['messages'][-1]['content']}
    fin = json.loads(results['t1']['content'])
    assert fin['cars'][0]['code'] == '621' and fin['cars'][0]['income'] == 13000   # rubles, not kopecks
    assert results['t4'].get('is_error') is True
    assert c.get('/api/v4/assistant/job/unknown', base_url=BASE).status_code == 404


def test_assistant_tools_never_see_personal_data():
    from dashboard.assistant import TOOLS
    names = {t['name'] for t in TOOLS}
    assert names.isdisjoint({'contracts', 'board', 'sql', 'wialon_command'})
    assert 'passport' not in json.dumps(TOOLS) and 'phone' not in json.dumps(TOOLS)


def test_assistant_off_without_key(fin_dash, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    c = make_app(fin_dash.engine_url).test_client()
    login(c)
    assert c.get('/api/v4/assistant', base_url=BASE).get_json()['enabled'] is False
    r = c.post('/api/v4/assistant', base_url=BASE, headers=csrf_headers(c), json={'message': 'привет'})
    assert r.status_code == 503 and 'ANTHROPIC_API_KEY' in r.get_json()['message']


def test_assistant_api_error_leaves_clean_conversation():
    from dashboard.assistant import Assistant

    def factory():
        raise RuntimeError('boom')
    a = Assistant({}, client_factory=factory, sync=True)
    job_id, conv_id = a.ask('owner', 'вопрос')
    assert a.job('owner', job_id)['status'] == 'error'
    assert a.job('someone-else', job_id) is None
    assert a.convs[conv_id]['messages'] == []
