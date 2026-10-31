import httpx
import pytest
from auth.emailer import send_email

@pytest.mark.parametrize('token_status,send_status,expected',[(200,202,None),(401,202,'authentication failed'),(200,403,'submission failed')])
def test_graph_delivery_contract(monkeypatch,token_status,send_status,expected):
    for key,value in {'MAIL_PROVIDER':'microsoft_graph','MAIL_FROM':'info@contractpros.co.uk','MS_TENANT_ID':'test-tenant','MS_CLIENT_ID':'test-client','MS_CLIENT_SECRET':'test-secret'}.items():
        monkeypatch.setenv(key,value)
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append((url,kwargs))
            return httpx.Response(token_status,json={'access_token':'test-token'}) if 'oauth2' in url else httpx.Response(send_status)
    monkeypatch.setattr('auth.emailer.httpx.Client',Client)
    if expected:
        with pytest.raises(RuntimeError,match=expected): send_email('test@example.com','Test','<p>Test</p>')
    else:
        send_email('test@example.com','Test','<p>Test</p>')
        assert calls[1][0]=='https://graph.microsoft.com/v1.0/users/info%40contractpros.co.uk/sendMail'
        assert calls[1][1]['json']['message']['toRecipients']==[{'emailAddress':{'address':'test@example.com'}}]
    assert len(calls)==(1 if token_status!=200 else 2)
