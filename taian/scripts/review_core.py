"""Verified household execution, isolated from credentials and terminal selection."""
import hashlib
import json
import os
from datetime import datetime, timezone

STATE = REPORT = AUDIT = None  # Bound to the selected task by run_review.


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def counts(client, batch, trustee):
    data = client.call(33, {'appraiseInfoCode': batch, 'appraiseTrusteeCode': trustee})['data']
    return {k: data[k] for k in ('residentNbr', 'residentStateOneNbr', 'residentStateTwoNbr')}


def households(client, batch, trustee, state):
    result = []
    total = None
    for page in range(1, 10001):
        data = client.call(32, {'appraiseInfoCode': batch, 'appraiseTrusteeCode': trustee,
                              'appraiseState': state, 'page': page, 'rows': 10})
        current_total = int(data['recordsTotal'])
        if total is None:
            total = current_total
        require(total == current_total, 'List changed during pagination; obtain a new stable snapshot')
        result.extend(data['data'])
        if len(result) >= total:
            break
        require(data['data'], 'Unexpected empty page')
    require(len(result) == total, 'Pagination count mismatch')
    require(len({x['householderIdNumber'] for x in result}) == total, 'Duplicate household in snapshot')
    return result


def detail(client, batch, trustee, house, state):
    return client.call(8, {'appraiseInfoCode': batch, 'trusteeCode': trustee,
                          'householderIdNumber': client.encrypt_house(house), 'appraiseState': state})['data']


def member_plan(rows):
    result = {}
    for row in rows:
        code = row['appraiseResidentCode']
        require(code and code not in result, 'Missing/duplicate member')
        elements = [x['appraiseInfoElementCode'] for x in row['list']]
        require(elements and len(elements) == len(set(elements)) and all(elements), 'Missing/duplicate element')
        result[code] = sorted(elements)
    return result


def verify(rows, expected):
    require(rows and expected, 'Empty result cannot pass detail verification')
    require(member_plan(rows) == expected, 'Readback member/element set mismatch')
    ids = []
    values = []
    for row in rows:
        require(row.get('appraiseTrusteeDetailId') is not None, 'Readback has no persisted detail ID')
        require(row.get('isUnderstand') is True and row.get('isSuitableCredit') is True, 'Readback member values mismatch')
        require(all(x.get('useElement') is True for x in row['list']), 'Readback element values mismatch')
        require(row.get('noSuitableCreditType') in (None, '', 'null'), 'Unexpected negative-credit reason')
        require(row.get('noSuitableCreditDesc') in (None, '', 'null'), 'Unexpected negative-credit description')
        ids.append(row['appraiseTrusteeDetailId'])
        values.append({'member': digest(row['appraiseResidentCode'])[:16], 'isUnderstand': row['isUnderstand'],
                       'isSuitableCredit': row['isSuitableCredit'], 'elementValues': [x['useElement'] for x in row['list']]})
    require(len(ids) == len(set(ids)), 'Duplicate persisted detail IDs')
    return {'members': len(rows), 'elements': sum(len(x['list']) for x in rows),
            'persistedDetailIdsDigest': digest(sorted(ids)),
            'memberValues': sorted(values, key=lambda x: x['member']), 'verified': True}


def run_selected(client, batch, target, roster_params, args):
    require(STATE is not None, '尚未绑定当前选择的任务台账。')
    roster = client.call(29, roster_params)['data']
    require(len([x for x in roster if x['code'] == target]) == 1, '所选评议员已不在当前名单中。')
    config = client.call(9, {'code': batch})['data']
    require(config.get('valid') is True and str(config.get('appraiseStatus')) == '0', '所选批次当前不可评议。')
    require(str(config.get('appraiseInfoType')) == '1' and str(config.get('markType')) == '0',
            '当前仅验证过首轮、要素模式评议；此批次类型暂不执行。')
    identity = {'baseUrl': client.base_url, 'enterprise': client.enterprise, 'userId': client.user_id}
    initial = {x['code']: {'status': x['selectStatus'], 'counts': counts(client, batch, x['code'])} for x in roster}
    pending = households(client, batch, target, 2)
    completed = households(client, batch, target, 1)
    public = {'target': digest(target)[:16], 'reviewers': [{'reviewer': digest(code)[:16], **v} for code, v in initial.items()],
              'targetPending': len(pending), 'targetCompleted': len(completed)}
    if not args.execute:
        for house in pending:
            rows = detail(client, batch, target, house['householderIdNumber'], 1)
            require(rows, 'Empty household detail')
            member_plan(rows)
        save(REPORT.with_name('preflight.json') if REPORT is not None else None, public)
        print(json.dumps(public, ensure_ascii=True))
        return
    require(args.test_values_from_recording, '未启用已确认的测试评议规则。')
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf-8'))
        require(state['identity'] == identity and state['ruleVersion'] == 'taian-all-true-v1', '运行身份或评议规则与台账不一致。')
        require(state['batch'] == batch and state['target'] == target, 'Existing state belongs to another task')
    else:
        if not pending and initial[target]['status'] == '3':
            public.update(complete=True, contentsVerified=False, writesThisInvocation=0,
                          message='该评议员已经完成，无新增写入；未将历史数据当作本次新增验收。')
            save(REPORT, public)
            print(public['message'])
            return
        require(initial[target]['status'] == '2' and pending, '评议员状态与待办不一致，未自动修改。')
        require(initial[target]['counts']['residentNbr'] == len(pending)+len(completed), '任务总户数与列表不一致。')
        state = {'schemaVersion':2, 'identity':identity, 'ruleVersion':'taian-all-true-v1',
                 'baselineCompleted':[h['householderIdNumber'] for h in completed],
                 'startedAt': datetime.now(timezone.utc).isoformat(), 'batch': batch, 'target': target,
                 'initial': initial, 'tasks': [], 'completion': 'pending',
                 'authorization': 'User confirmed all-true test values; batch and reviewer selected interactively'}
        for house in pending:
            rows = detail(client, batch, target, house['householderIdNumber'], 1)
            expected = member_plan(rows)
            require(expected, 'Empty member plan')
            state['tasks'].append({'house': house['householderIdNumber'], 'expected': expected, 'status': 'pending'})
        save(STATE, state)
    writes_this_run = 0
    for task in state['tasks']:
        house = task['house']
        existing = detail(client, batch, target, house, 2)
        if existing:
            task['verification'] = verify(existing, task['expected'])
            task['status'] = 'verified'
            save(STATE, state)
            continue
        require(task['status'] == 'pending', 'Unknown prior write cannot be automatically retried')
        rows = detail(client, batch, target, house, 1)
        require(member_plan(rows) == task['expected'], 'Household changed after snapshot')
        payload = {'appraiseInfoCode': batch, 'appraiseTrusteeCode': target}
        for i, row in enumerate(rows):
            prefix = 'list[%d].' % i
            payload.update({prefix+'appraiseResidentCode': row['appraiseResidentCode'],
                            prefix+'isUnderstand': 'true', prefix+'isSuitableCredit': 'true',
                            prefix+'noSuitableCreditType': '', prefix+'noSuitableCreditDesc': 'null', prefix+'remarks': ''})
            for j, element in enumerate(row['list']):
                payload[prefix+'list[%d].appraiseInfoElementCode' % j] = element['appraiseInfoElementCode']
                payload[prefix+'list[%d].isUseElement' % j] = 'true'
        task['status'] = 'unknown'
        task['requestDigest'] = digest(payload)
        save(STATE, state)
        client.call(11, payload, write=True)
        task['verification'] = verify(detail(client, batch, target, house, 2), task['expected'])
        task['status'] = 'verified'
        save(STATE, state)
        writes_this_run += 1
        print(json.dumps({'household': digest(house)[:16], 'verifiedMembers': len(rows), 'progress': sum(t['status']=='verified' for t in state['tasks'])}), flush=True)
        if args.limit and writes_this_run >= args.limit:
            break
    all_verified = all(t['status'] == 'verified' for t in state['tasks'])
    if all_verified:
        require(not households(client, batch, target, 2), 'Pending households remain; completion forbidden')
        actual_done = households(client, batch, target, 1)
        require({h['householderIdNumber'] for h in actual_done} == {t['house'] for t in state['tasks']} | set(state['baselineCompleted']), 'Completed household set mismatch')
        require(counts(client, batch, target) == {'residentNbr':len(state['tasks'])+len(state['baselineCompleted']), 'residentStateOneNbr':len(state['tasks'])+len(state['baselineCompleted']), 'residentStateTwoNbr':0}, 'Final target counts mismatch')
        fresh = client.call(29, roster_params)['data']
        require({x['code'] for x in fresh} == set(initial), 'Roster changed')
        for person in fresh:
            if person['code'] != target:
                require({'status':person['selectStatus'],'counts':counts(client,batch,person['code'])} == initial[person['code']], 'Another reviewer changed')
        current = next(x for x in fresh if x['code'] == target)
        if current['selectStatus'] != '3':
            require(current['selectStatus'] == '2' and state['completion'] == 'pending', 'Unknown completion state')
            payload = dict(roster_params)
            for i, person in enumerate(fresh):
                for field in ('personName','idNum','selectStatus','historyStatus','pretrialStatus'):
                    value = '3' if person['code'] == target and field == 'selectStatus' else person.get(field)
                    payload['trusteeList[%d].%s' % (i,field)] = 'null' if value is None else str(value)
            state['completion'] = 'unknown'
            save(STATE, state)
            client.call(28, payload, write=True)
        after_roster = client.call(29, roster_params)['data']
        require(next(x for x in after_roster if x['code']==target)['selectStatus']=='3', 'Completion status not persisted')
        for task in state['tasks']:
            recheck = verify(detail(client,batch,target,task['house'],2), task['expected'])
            require(recheck == task['verification'], 'Completion changed persisted detail records')
        state['completion'] = 'verified'
        save(STATE,state)
    final_roster = client.call(29,roster_params)['data']
    final = {x['code']:{'status':x['selectStatus'],'counts':counts(client,batch,x['code'])} for x in final_roster}
    require(set(final) == set(initial), 'Roster membership changed')
    for code in final:
        if code != target:
            require(final[code] == initial[code], 'Untargeted reviewer changed')
    result = {'verifiedAt':datetime.now(timezone.utc).isoformat(),'ruleVersion':state['ruleVersion'],
              'target':digest(target)[:16], 'complete':state['completion']=='verified',
              'householdsVerified':sum(t['status']=='verified' for t in state['tasks']),
              'membersVerified':sum(len(t['expected']) for t in state['tasks'] if t['status']=='verified'),
              'writesThisInvocation':client.writes,
              'before':[{'reviewer':digest(k)[:16],**v} for k,v in initial.items()],
              'after':[{'reviewer':digest(k)[:16],**v} for k,v in final.items()],
              'tasks':[{'household':digest(t['house'])[:16],'status':t['status'],'verification':t.get('verification')} for t in state['tasks']],
              'untargetedReviewersUnchanged':True,'wholeBatchSubmitted':False,
              'limitations':['All-true first-round element scenario only','No database or browser visual validation','No 1000-household or concurrent run']}
    successful_writes = client.events
    successful_writes = [e for e in successful_writes if e.get('write') and e.get('businessCode') == '0']
    result['successfulWritesThisSession'] = len(successful_writes)
    result['successfulWriteBreakdown'] = {
        'householdSaves':sum(e['recordingTemplate']==11 for e in successful_writes),
        'reviewerCompletionSaves':sum(e['recordingTemplate']==28 for e in successful_writes)}
    save(REPORT,result)
    print(json.dumps({k:result[k] for k in ('complete','householdsVerified','membersVerified','writesThisInvocation','untargetedReviewersUnchanged')},ensure_ascii=True))


