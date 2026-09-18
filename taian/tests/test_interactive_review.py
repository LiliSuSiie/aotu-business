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
import review_core as core
from run_review import run_workflow


class Server:
    def __init__(self):
        self.requests, self.writes = [], []
        self.login_count = 0
        self.bad_login = False
        self.omit_token = False
        self.expire_business = False
        self.drop_after_save = False
        self.drop_after_finish = False
        self.appraise_type = '1'
        self.mark_type = '0'
        self.household_writes = []
        self.historical = {}
        self.non_object_response = False
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
                    if owner.drop_after_finish and url.path.endswith('/info/resident/save'):
                        owner.drop_after_finish=False
                        status=503
                    raw=json.dumps({'code':code,'data':data,'recordsTotal':total,'requestId':'mock-request'}).encode()
                    if owner.non_object_response:
                        raw=b'[]'
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
            return {'valid':True,'appraiseStatus':0,'appraiseInfoType':self.appraise_type,'markType':self.mark_type},0,'0'
        if path.endswith('/info/trustee/list'):
            return deepcopy(self.roster),0,'0'
        if path.endswith('/info/resident'):
            target=p['appraiseTrusteeCode']
            done=len(self.done[target] | self.historical.get(target,set()))
            return {'residentNbr':12,'residentStateOneNbr':done,'residentStateTwoNbr':12-done},0,'0'
        if path.endswith('/info/resident/list'):
            target=p['appraiseTrusteeCode']
            done=self.done[target] | self.historical.get(target,set())
            houses=[x for x in self.houses if (x in done)==(p['appraiseState']=='1')]
            page,size=int(p['page']),int(p['rows'])
            rows=[{'householderIdNumber':x,'historyStatus':'1' if x in self.historical.get(target,set()) else None}
                  for x in houses[(page-1)*size:page*size]]
            return rows,len(rows) if self.appraise_type=='4' else len(houses),'0'
        if path.endswith('/trustee/detail/info'):
            matched=[x for x in self.houses if encrypt(x)==p['householderIdNumber']]
            assert len(matched)==1, 'household must be encrypted'
            house=matched[0]
            if p['appraiseState']=='2' and house not in self.done[p['trusteeCode']]:
                return [],0,'0'
            saved=house in self.done[p['trusteeCode']]
            history=self.appraise_type in ('2','4') and not saved
            return [{'appraiseResidentCode':house,'appraiseTrusteeDetailId':self.houses.index(house)+1 if saved else (9999 if history else None),
                     'historyAppraiseData':'1' if history else None,
                     'isUnderstand':True if saved or history else None,'isSuitableCredit':True if saved or history else None,
                     'noSuitableCreditType':None,'noSuitableCreditDesc':None,
                     'list':[{'appraiseInfoElementCode':'element-%d'%i,'useElement':True if saved or history else None} for i in range(3)]}],0,'0'
        if path.endswith('/trustee/detail/save'):
            target=p['appraiseTrusteeCode']
            house=p['list[0].appraiseResidentCode']
            assert house not in self.done[target], 'duplicate save'
            assert house not in self.historical.get(target,set()), 'historical completed household must be preserved'
            assert p['list[0].isUnderstand']==p['list[0].isSuitableCredit']=='true'
            for i in range(3):
                assert p['list[0].list[%d].appraiseInfoElementCode'%i]=='element-%d'%i
                assert p['list[0].list[%d].isUseElement'%i]=='true'
            self.done[target].add(house)
            self.writes.append(('house',house))
            self.household_writes.append((target,house))
            return None,0,'0'
        if path.endswith('/info/resident/save'):
            changed=[]
            for i,x in enumerate(self.roster):
                for field in ('personName','idNum','historyStatus','pretrialStatus'):
                    assert p['trusteeList[%d].%s'%(i,field)]==x[field]
                status=p['trusteeList[%d].selectStatus'%i]
                if status != x['selectStatus']:
                    assert status=='3' and x['selectStatus']=='2'
                    assert len(self.done[x['code']] | self.historical.get(x['code'],set()))==12
                    changed.append(x)
            assert len(changed)==1, 'only selected reviewer may change'
            changed[0]['selectStatus']='3'
            self.writes.append(('finish',changed[0]['code']))
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

    def run_flow(self, answers=('b11','r2'), limit=0, dry=False, no_report=False):
        values=iter(answers)
        args=SimpleNamespace(config=self.path,dry_run=dry,limit=limit,no_report=no_report)
        self.prompts, self.messages = [], []
        def answer(prompt):
            self.prompts.append(prompt)
            value=next(values)  # Unexpected prompts intentionally fail the test.
            if value is EOFError:
                raise EOFError
            return value
        with contextlib.redirect_stdout(io.StringIO()):
            return run_workflow(args,input_fn=answer,output=self.messages.append,root=self.root)

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
        folder=self.run_flow(answers=('b11','r1','n'))
        self.assertEqual(json.loads((folder/'result.json').read_text(encoding='utf8'))['writesThisInvocation'],0)
        self.assertEqual(len(self.server.writes),1)
        saved=json.loads(next((self.root/'state').rglob('*.json')).read_text(encoding='utf8'))
        self.assertEqual(saved['target'],'r2')

    def three_pending(self):
        self.server.roster.append({'code':'r3','personName':'Third reviewer','idNum':'reviewer-three',
                                   'selectStatus':'2','historyStatus':'null','pretrialStatus':'2'})
        for row in self.server.roster:
            row['selectStatus']='2'
            self.server.done[row['code']]=set()

    def assert_three_reviewers_complete(self, kind):
        self.three_pending()
        self.server.appraise_type=kind
        folder=self.run_flow(('b11','r2','invalid','y','r1','y','r3'))
        self.assertEqual(self.server.login_count,1)
        self.assertTrue(all(p['selectStatus']=='3' for p in self.server.roster))
        self.assertEqual(len(self.server.household_writes),36)
        self.assertEqual(len(set(self.server.household_writes)),36)
        self.assertEqual([x for x in self.server.writes if x[0]=='finish'],[('finish','r2'),('finish','r1'),('finish','r3')])
        self.assertEqual(len(list((self.root/'state').rglob('*.json'))),3)
        reports=[json.loads(p.read_text(encoding='utf8')) for p in (folder/'reviewers').glob('*.json')]
        self.assertEqual(len(reports),3)
        self.assertTrue(all(r['writesThisInvocation']==13 for r in reports))
        self.assertTrue(all(r['successfulWriteBreakdown']=={'householdSaves':12,'reviewerCompletionSaves':1} for r in reports))
        self.assertIn('本批次所有参与评议的人员均已完成，无需继续选择。',self.messages)
        self.assertFalse(list((self.root/'state').rglob('*.lock')))

    def test_first_round_continues_three_reviewers_and_stops_without_extra_prompt(self):
        self.assert_three_reviewers_complete('1')

    def test_type_two_continues_three_reviewers_and_stops_without_extra_prompt(self):
        self.assert_three_reviewers_complete('2')

    def test_type_four_paginates_and_continues_three_reviewers(self):
        self.assert_three_reviewers_complete('4')

    def test_type_four_preserves_historical_households_and_only_saves_pending(self):
        self.server.appraise_type='4'
        self.server.done['r2']=set()
        self.server.historical['r2']=set(self.server.houses[:11])
        folder=self.run_flow()
        result=json.loads((folder/'result.json').read_text(encoding='utf8'))
        self.assertEqual(self.server.household_writes,[('r2',self.server.houses[-1])])
        self.assertEqual(result['baselineCompletedHouseholds'],11)
        self.assertEqual(result['householdsVerified'],1)
        self.assertEqual(result['writesThisInvocation'],2)
        self.assertTrue(result['complete'])
        self.assertEqual(self.server.historical['r2'],set(self.server.houses[:11]))

    def test_type_four_all_historical_only_finishes_and_recovers_unknown_finish(self):
        self.three_pending()
        self.server.appraise_type='4'
        self.server.historical['r2']=set(self.server.houses)
        self.run_flow(('b11','r2'),dry=True,no_report=True)
        self.assertEqual(self.server.writes,[])
        self.server.drop_after_finish=True
        with self.assertRaises(RuntimeError):
            self.run_flow(no_report=True)
        self.assertEqual(self.server.writes,[('finish','r2')])
        self.run_flow(('b11','r2','n'),no_report=True)
        self.assertEqual(self.server.writes,[('finish','r2')])
        state=json.loads(next((self.root/'state').rglob('*.json')).read_text(encoding='utf8'))
        self.assertEqual(state['tasks'],[])
        self.assertEqual(state['completion'],'verified')

    def test_type_four_unknown_household_save_resumes_without_duplicates(self):
        self.server.appraise_type='4'
        self.server.historical['r2']=set(self.server.houses[1:4])
        self.server.drop_after_save=True
        with self.assertRaises(RuntimeError):
            self.run_flow(no_report=True)
        self.run_flow(no_report=True)
        self.assertEqual(len(self.server.household_writes),8)
        self.assertEqual(len(set(self.server.household_writes)),8)
        self.assertEqual(self.server.roster[1]['selectStatus'],'3')

    def test_type_four_repeated_or_missing_page_blocks_writes(self):
        self.server.appraise_type='4'
        original=self.server.dispatch
        for missing in (False,True):
            def bad_page(path,params,headers):
                if path.endswith('/info/resident/list') and params['page']=='2':
                    if missing:
                        return [],0,'0'
                    params=dict(params,page='1')
                return original(path,params,headers)
            self.server.dispatch=bad_page
            with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError,'Duplicate|empty page'):
                self.run_flow(no_report=True)
        self.assertEqual(self.server.writes,[])

    def test_no_stops_with_other_reviewers_untouched_and_no_reports(self):
        self.three_pending()
        self.run_flow(('b11','r2','n'),no_report=True)
        self.assertEqual(self.server.done['r1'],set())
        self.assertEqual(self.server.done['r3'],set())
        self.assertEqual(self.server.roster[1]['selectStatus'],'3')
        self.assertFalse((self.root/'reports').exists())
        self.assertEqual(len(list((self.root/'state').rglob('*.json'))),1)

    def test_eof_at_continuation_preserves_completed_reviewer(self):
        self.three_pending()
        self.run_flow(('b11','r2',EOFError),no_report=True)
        self.assertEqual(len(self.server.writes),13)
        self.assertFalse(list((self.root/'state').rglob('*.lock')))

    def test_all_done_at_start_does_not_ask_for_reviewer(self):
        self.server.done['r2']=set(self.server.houses)
        self.server.roster[1]['selectStatus']='3'
        self.run_flow(('b11',),no_report=True)
        self.assertEqual(len(self.prompts),1)
        self.assertEqual(self.server.writes,[])

    def test_limit_and_dry_run_never_prompt_to_continue(self):
        self.three_pending()
        self.run_flow(('b11','r2'),dry=True,no_report=True)
        self.assertEqual(self.server.writes,[])
        self.run_flow(('b11','r2'),limit=1,no_report=True)
        self.assertEqual(len(self.server.writes),1)
        self.assertEqual(len(self.prompts),2)

    def test_unsupported_types_and_mark_mode_never_write(self):
        for kind,mark in [('3','0'),('5','0'),('2','1'),('4','1')]:
            self.server.appraise_type,self.server.mark_type=kind,mark
            with self.subTest(kind=kind,mark=mark), self.assertRaisesRegex(RuntimeError,'仅支持'):
                self.run_flow(no_report=True)
        self.assertEqual(self.server.writes,[])
        self.assertFalse(list((self.root/'state').rglob('*.lock')))

    def test_completion_503_resumes_without_duplicate_save(self):
        self.three_pending()
        self.server.drop_after_finish=True
        with self.assertRaises(RuntimeError):
            self.run_flow(('b11','r2'),no_report=True)
        state_path=next((self.root/'state').rglob('*.json'))
        self.assertEqual(json.loads(state_path.read_text(encoding='utf8'))['completion'],'unknown')
        self.run_flow(('b11','r2','n'),no_report=True)
        self.assertEqual(len(self.server.writes),13)
        self.assertEqual(json.loads(state_path.read_text(encoding='utf8'))['completion'],'verified')

    def test_corrupt_and_duplicate_task_state_block_new_writes(self):
        self.run_flow(limit=1,no_report=True)
        state_path=next((self.root/'state').rglob('*.json'))
        original=json.loads(state_path.read_text(encoding='utf8'))
        duplicate=deepcopy(original)
        duplicate['tasks'].append(deepcopy(duplicate['tasks'][0]))
        for content in ('{bad json',json.dumps(duplicate)):
            state_path.write_text(content,encoding='utf8')
            with self.assertRaisesRegex(RuntimeError,'台账'):
                self.run_flow(no_report=True)
        self.assertEqual(len(self.server.writes),1)

    def test_existing_lock_blocks_writes_without_removing_lock(self):
        scope=core.digest([self.server.base,'enterprise-new','b11'])[:32]
        lock=self.root/'state'/'interactive'/scope/'batch.lock'
        lock.parent.mkdir(parents=True)
        lock.write_text('another process',encoding='ascii')
        with self.assertRaisesRegex(RuntimeError,'运行锁'):
            self.run_flow(no_report=True)
        self.assertEqual(lock.read_text(encoding='ascii'),'another process')
        self.assertEqual(self.server.writes,[])

    def test_invalid_roster_counts_and_envelope_block_writes(self):
        original=self.server.dispatch
        def bad_counts(path,params,headers):
            data,total,code=original(path,params,headers)
            if path.endswith('/info/resident'):
                data['residentStateTwoNbr']=-1
            return data,total,code
        self.server.dispatch=bad_counts
        with self.assertRaisesRegex(RuntimeError,'负数'):
            self.run_flow(no_report=True)
        self.server.dispatch=original
        self.server.roster.append(deepcopy(self.server.roster[0]))
        with self.assertRaisesRegex(RuntimeError,'重复'):
            self.run_flow(no_report=True)
        self.server.roster.pop()
        self.server.non_object_response=True
        with self.assertRaisesRegex(RuntimeError,'格式异常'):
            self.run_flow(no_report=True)
        self.assertEqual(self.server.writes,[])

    def test_failed_readback_stops_before_completion_and_next_reviewer(self):
        self.three_pending()
        original=self.server.dispatch
        def mismatch(path,params,headers):
            data,total,code=original(path,params,headers)
            if path.endswith('/trustee/detail/info') and params['appraiseState']=='2' and data:
                data[0]['isSuitableCredit']=False
            return data,total,code
        self.server.dispatch=mismatch
        with self.assertRaisesRegex(RuntimeError,'mismatch'):
            self.run_flow(('b11','r2'),no_report=True)
        self.assertEqual(len(self.server.writes),1)
        self.assertTrue(all(p['selectStatus']=='2' for p in self.server.roster))
        self.assertEqual(len(self.prompts),2)

    def test_unknown_write_without_readback_is_not_retried(self):
        self.server.drop_after_save=True
        with self.assertRaises(RuntimeError):
            self.run_flow(no_report=True)
        saved_house=self.server.household_writes[0][1]
        self.server.done['r2'].remove(saved_house)
        with self.assertRaisesRegex(RuntimeError,'cannot be automatically retried'):
            self.run_flow(no_report=True)
        self.assertEqual(len(self.server.writes),1)

    def test_verified_details_changed_on_resume_block_remaining_writes(self):
        self.run_flow(limit=1,no_report=True)
        original=self.server.dispatch
        def changed_id(path,params,headers):
            data,total,code=original(path,params,headers)
            if path.endswith('/trustee/detail/info') and params['appraiseState']=='2' and data:
                data[0]['appraiseTrusteeDetailId']+=1000
            return data,total,code
        self.server.dispatch=changed_id
        with self.assertRaisesRegex(RuntimeError,'明细发生变化'):
            self.run_flow(no_report=True)
        self.assertEqual(len(self.server.writes),1)

    def test_changed_household_snapshot_blocks_resume(self):
        self.run_flow(limit=1,no_report=True)
        self.server.houses[-1]='new-house'
        self.server.done['r1']=set(self.server.houses)
        with self.assertRaisesRegex(RuntimeError,'户清单已变化'):
            self.run_flow(no_report=True)
        self.assertEqual(len(self.server.writes),1)

    def test_historical_readback_cannot_pass_current_batch_verification(self):
        self.server.appraise_type='2'
        original=self.server.dispatch
        def historical_readback(path,params,headers):
            data,total,code=original(path,params,headers)
            if path.endswith('/trustee/detail/info') and params['appraiseState']=='2' and data:
                data[0]['historyAppraiseData']='1'
            return data,total,code
        self.server.dispatch=historical_readback
        with self.assertRaisesRegex(RuntimeError,'历史评议结果'):
            self.run_flow(no_report=True)
        self.assertEqual(len(self.server.writes),1)
        self.assertEqual(self.server.roster[1]['selectStatus'],'2')

    def test_roster_is_refreshed_after_user_chooses_continue(self):
        self.three_pending()
        values=iter(('b11','r2'))
        def answer(prompt):
            if '是否继续' in prompt:
                # Another operator finishes the rest while this terminal waits.
                for row in self.server.roster:
                    row['selectStatus']='3'
                    self.server.done[row['code']]=set(self.server.houses)
                return 'y'
            return next(values)
        args=SimpleNamespace(config=self.path,dry_run=False,limit=0,no_report=True)
        with contextlib.redirect_stdout(io.StringIO()):
            run_workflow(args,input_fn=answer,output=lambda _:None,root=self.root)
        self.assertEqual(len(self.server.writes),13)


if __name__=='__main__':
    unittest.main(verbosity=2)
