import runpy
from pathlib import Path


def test_demo_seed_is_idempotent_and_does_not_reset_password(monkeypatch, capsys):
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'seed_demo_user.py'))
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'server-test-key')
    monkeypatch.setenv('ENABLE_DEMO_USER', 'true')
    users=[]; created_passwords=[]; profiles=[]

    class Response:
        def __init__(self, body): self.body=body
        def json(self): return self.body

    def fake_request(method, url, key, **kwargs):
        if method == 'GET': return Response({'users': users})
        if method == 'POST' and '/admin/users' in url:
            created_passwords.append(kwargs['json']['password'])
            user={'id':'user-1','email':'test@users.sif-sentinel.invalid'}; users.append(user); return Response(user)
        profiles.append(kwargs['json']); return Response({})

    monkeypatch.setitem(module['main'].__globals__, 'request', fake_request)
    module['main'](); module['main']()
    assert created_passwords == ['test123']
    assert profiles[-1]['username'] == 'test' and profiles[-1]['role'] == 'reviewer'
    assert 'password was not changed' in capsys.readouterr().out
