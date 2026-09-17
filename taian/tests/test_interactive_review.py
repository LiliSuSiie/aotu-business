"""Offline HTTP integration tests. Never calls the recorded business server."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_client import Client, batch_list, choose, encrypt, load_config
from run_review import run_workflow


class Server:
    def __init__(self):
        self.requests, self.writes = [], []
        self.login_count = 0
        self.bad_login = False
        self.omit_token = False
        self.expire_business = False
        self.drop_after_save = False
        self.rows = [{'code':'b%d'%i, 'villageName':'Batch %d'%i, 'appraiseStatus':0,
                      'appraiseInfoType':'1'} for i in range(12)]
        self.roster = [{'code':'r1','personName':'Already done','idNum':'reviewer-one','selectStatus':'3',
                        'historyStatus':'null','pretrialStatus':'2'},
                       {'code':'r2','personName':'Selected reviewer','idNum':'reviewer-two','selectStatus':'2',
                        'historyStatus':'null','pretrialStatus':'2'}]
        self.houses = ['house-%02d'%i for i in range(12)]
        self.done = {'r1':set(self.houses),'r2':{self.houses[0]}}
        self.target_batches = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                url = urllib.parse.urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get('Content-Length','0'))).decode()
                params = dict(urllib.parse.parse_qsl(body or url.query,keep_blank_values=True))
                owner.requests.append((url.path,params,dict(self.headers)))
                try:
                    data, total, code = owner.dispatch(url.path,params,self.headers)
                    status=200
                    if owner.drop_after_save and url.path.endswith('/trustee/detail/save'):
                        owner.drop_after_save=False
                        status=503
                    raw=json.dumps({'code':code,'data':data,'recordsTotal':total,'requestId':'mock-request'}).encode()
                except AssertionError:
                    status=400
                    raw=b'{"code":"CONTRACT_FAILURE"}'
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:%s/backend'%self.http.server_port

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def dispatch(self,path,p,h):
        if path.endswith('/user/login'):
            self.login_count+=1
            assert h.get('Authorization','')==''
            assert p['userName']=='c4d94d84638ff343fbc6aa700906a5e6'
            # Verify plaintext recovery independently at the mock server boundary.
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            password=unpad(AES.new(b'1234567890ABCDEF',AES.MODE_ECB).decrypt(bytes.fromhex(p['password'])),16).decode()
            assert password=='mock-secret-密码'
            assert p['loginType']=='4' and p['smsType']=='H5'
            if self.bad_login:
                return None,0,'LOGIN_DENIED'
            data={'userId':7,'enterpCode':'enterprise-new'}
            if not self.omit_token:
                data['token']='fresh-token-%d'%self.login_count
            return data,0,'0'
        assert h.get('Authorization')=='fresh-token-%d'%self.login_count
        assert h.get('EnterpriseCode')=='enterprise-new'
        if self.expire_business:
            return None,0,'SESSION_EXPIRED'
        if path.endswith('/appraise/info/list'):
            page,size=int(p['page']),int(p['rows'])
            return self.rows[(page-1)*size:page*size],0,'0'
        assert p.get('appraiseInfoCode',p.get('code'))=='b11'
        self.target_batches.append(p.get('appraiseInfoCode',p.get('code')))
        if path.endswith('/appraise/info/type'):
            return {'valid':True,'appraiseStatus':0,'appraiseInfoType':'1','markType':0},0,'0'
        if path.endswith('/info/trustee/list'):
            return deepcopy(self.roster),0,'0'
        if path.endswith('/info/resident'):
            done=len(self.done[p['appraiseTrusteeCode']])
            return {'residentNbr':12,'residentStateOneNbr':done,'residentStateTwoNbr':12-done},0,'0'
        if path.endswith('/info/resident/list'):
            done=self.done[p['appraiseTrusteeCode']]
            houses=[x for x in self.houses if (x in done)==(p['appraiseState']=='1')]
            page,size=int(p['page']),int(p['rows'])
            return [{'householderIdNumber':x} for x in houses[(page-1)*size:page*size]],len(houses),'0'
        if path.endswith('/trustee/detail/info'):
            matched=[x for x in self.houses if encrypt(x)==p['householderIdNumber']]
            assert len(matched)==1, 'household must be encrypted'
            house=matched[0]
            if p['appraiseState']=='2' and house not in self.done[p['trusteeCode']]:
                return [],0,'0'
            saved=house in self.done[p['trusteeCode']]
            return [{'appraiseResidentCode':house,'appraiseTrusteeDetailId':self.houses.index(house)+1 if saved else None,
                     'isUnderstand':True if saved else None,'isSuitableCredit':True if saved else None,
                     'noSuitableCreditType':None,'noSuitableCreditDesc':None,
                     'list':[{'appraiseInfoElementCode':'element-%d'%i,'useElement':True if saved else None} for i in range(3)]}],0,'0'
        if path.endswith('/trustee/detail/save'):
            assert p['appraiseTrusteeCode']=='r2'
            house=p['list[0].appraiseResidentCode']
            assert house not in self.done['r2'], 'duplicate save'
            assert p['list[0].isUnderstand']==p['list[0].isSuitableCredit']=='true'
            for i in range(3):
                assert p['list[0].list[%d].appraiseInfoElementCode'%i]=='element-%d'%i
                assert p['list[0].list[%d].isUseElement'%i]=='true'
            self.done['r2'].add(house)
            self.writes.append(('house',house))
            return None,0,'0'
        if path.endswith('/info/resident/save'):
            assert len(self.done['r2'])==12
            for i,x in enumerate(self.roster):
                for field in ('personName','idNum','historyStatus','pretrialStatus'):
                    assert p['trusteeList[%d].%s'%(i,field)]==x[field]
                assert p['trusteeList[%d].selectStatus'%i]=='3'
            self.roster[1]['selectStatus']='3'
            self.writes.append(('finish','r2'))
            return None,0,'0'
        raise AssertionError('Unexpected endpoint')


class InteractiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.server=Server()
        self.config={'baseUrl':self.server.base,'username':'hh01','password':'mock-secret-密码'}
        self.path=self.root/'config.json'
        self.path.write_text(json.dumps(self.config),encoding='utf8')

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def run_flow(self, answers=('b11','r2'), limit=0, dry=False):
        values=iter(answers)
        args=SimpleNamespace(config=self.path,dry_run=dry,limit=limit)
        with contextlib.redirect_stdout(io.StringIO()):
            return run_workflow(args,input_fn=lambda _:next(values),output=lambda _:None,root=self.root)

    def test_known_aes_vector_and_missing_password(self):
        self.assertEqual(encrypt('hh01'),'c4d94d84638ff343fbc6aa700906a5e6')
        self.path.write_text('{"username":"hh01","password":""}',encoding='utf8')
        with self.assertRaisesRegex(RuntimeError,'password'):
            self.run_flow()
        self.assertEqual(self.server.requests,[])

    def test_menu_reprompts_and_accepts_code(self):
        values=iter(['','999','b'])
        choice=choose('test',[{'code':'a'},{'code':'b'}],lambda x:x['code'],lambda _:next(values),lambda _:None)
        self.assertEqual(choice['code'],'b')
        with self.assertRaises(KeyboardInterrupt):
            choose('test',[{'code':'a'}],lambda x:x['code'],lambda _:'q',lambda _:None)
        def eof(_): raise EOFError
        with self.assertRaisesRegex(RuntimeError,'未自动选择'):
            choose('test',[{'code':'a'}],lambda x:x['code'],eof,lambda _:None)

    def test_new_login_each_time_and_pagination_with_zero_total(self):
        c=Client(self.config,self.root/'audit.jsonl')
        c.login()
        self.assertEqual(len(batch_list(c)),12)
        c.login()
        self.assertEqual(len(batch_list(c)),12)
        self.assertEqual(self.server.login_count,2)
        self.assertEqual(c.headers['Authorization'],'fresh-token-2')

    def test_bad_login_and_missing_token_block_all_business_calls(self):
        for flag in ('bad_login','omit_token'):
            setattr(self.server,flag,True)
            with self.assertRaises(RuntimeError):self.run_flow()
            setattr(self.server,flag,False)
        self.assertTrue(all(path.endswith('/user/login') for path,_,_ in self.server.requests))
        self.assertEqual(self.server.writes,[])

    def test_dry_run_selects_second_reviewer_without_writes(self):
        folder=self.run_flow(answers=('12','2'),dry=True)
        self.assertTrue((folder/'preflight.json').exists())
        self.assertEqual(self.server.writes,[])
        self.assertEqual(set(self.server.target_batches),{'b11'})

    def test_execute_resume_finish_and_zero_write_rerun(self):
        original=deepcopy(self.server.roster[0])
        first=self.run_flow(limit=1)
        self.assertFalse(json.loads((first/'result.json').read_text(encoding='utf8'))['complete'])
        self.assertEqual(len(self.server.writes),1)
        second=self.run_flow()
        result=json.loads((second/'result.json').read_text(encoding='utf8'))
        self.assertTrue(result['complete'])
        self.assertEqual(result['householdsVerified'],11)  # plus one pre-existing completed household
        self.assertEqual(len(self.server.writes),12)       # 11 saves + 1 finish
        last=self.run_flow()
        self.assertEqual(json.loads((last/'result.json').read_text(encoding='utf8'))['writesThisInvocation'],0)
        self.assertEqual(len(self.server.writes),12)
        self.assertEqual(self.server.roster[0],original)
        self.assertEqual(len(list((self.root/'state').rglob('*.json'))),1)
        reports='\n'.join(p.read_text(encoding='utf8') for p in (self.root/'reports').rglob('*') if p.is_file())
        for secret in ('mock-secret-密码',encrypt('mock-secret-密码'),encrypt('hh01'),'fresh-token-1','fresh-token-2','fresh-token-3'):
            self.assertNotIn(secret,reports)

    def test_write_503_is_not_retried_and_resume_reconciles(self):
        self.server.drop_after_save=True
        with self.assertRaises(RuntimeError):self.run_flow()
        self.assertEqual(len(self.server.writes),1)
        saved=json.loads(next((self.root/'state').rglob('*.json')).read_text(encoding='utf8'))
        self.assertEqual(saved['tasks'][0]['status'],'unknown')
        final=self.run_flow()
        self.assertTrue(json.loads((final/'result.json').read_text(encoding='utf8'))['complete'])
        self.assertEqual(len(self.server.writes),12)

    def test_session_expiry_stops_without_relogin_or_write(self):
        self.server.expire_business=True
        with self.assertRaises(RuntimeError):self.run_flow()
        self.assertEqual(self.server.login_count,1)
        self.assertEqual(self.server.writes,[])

    def test_different_reviewer_does_not_reuse_pending_state(self):
        self.run_flow(limit=1)
        folder=self.run_flow(answers=('b11','r1'))
        self.assertEqual(json.loads((folder/'result.json').read_text(encoding='utf8'))['writesThisInvocation'],0)
        self.assertEqual(len(self.server.writes),1)
        saved=json.loads(next((self.root/'state').rglob('*.json')).read_text(encoding='utf8'))
        self.assertEqual(saved['target'],'r2')


if __name__=='__main__':
    unittest.main(verbosity=2)
