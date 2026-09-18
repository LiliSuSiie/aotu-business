"""Verified household execution, isolated from credentials and terminal selection."""
import hashlib
import json
import os
from datetime import datetime, timezone

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
    data = client.call(33, {'appraiseInfoCode': batch, 'appraiseTrusteeCode': trustee}).get('data')
    require(isinstance(data, dict), '评议户数统计格式异常。')
    result = {k: nonnegative_int(data.get(k), '评议户数统计')
              for k in ('residentNbr', 'residentStateOneNbr', 'residentStateTwoNbr')}
    require(result['residentNbr'] == result['residentStateOneNbr'] + result['residentStateTwoNbr'],
            '评议总户数与已办、待办数量不一致，请重新查询。')
    return result


def nonnegative_int(value, label):
    require(type(value) is int or (isinstance(value, str) and value.isascii() and value.isdecimal()
                                 and len(value) <= 10), label + '必须为非负整数。')
    result = int(value)
    require(result >= 0, label + '不能为负数。')
    return result


def identifier(value):
    return isinstance(value, str) and bool(value.strip())


def get_roster(client, params):
    rows = client.call(29, params).get('data')
    require(isinstance(rows, list), '评议员列表格式异常。')
    seen = set()
    for row in rows:
        require(isinstance(row, dict), '评议员条目格式异常。')
        code = row.get('code')
        require(identifier(code) and code not in seen, '评议员列表包含缺失或重复 code。')
        require(str(row.get('selectStatus')) in ('1', '2', '3'), '评议员状态异常。')
        row['selectStatus'] = str(row['selectStatus'])
        seen.add(code)
    return rows


def households(client, batch, trustee, state, supplement=False):
    result = []
    snapshot = counts(client, batch, trustee) if supplement else None
    # Supplementary queries paginate household IDs, then return a plain List.
    # PageInfo on that List can expose only the current page size as recordsTotal.
    count_key = 'residentStateTwoNbr' if state == 2 else 'residentStateOneNbr'
    total = snapshot[count_key] if supplement else None
    seen = set()
    for page in range(1, 10001):
        data = client.call(32, {'appraiseInfoCode': batch, 'appraiseTrusteeCode': trustee,
                              'appraiseState': state, 'page': page, 'rows': 10})
        current_total = nonnegative_int(data.get('recordsTotal'), '户列表总数')
        rows = data.get('data')
        require(isinstance(rows, list) and all(isinstance(x, dict) and identifier(x.get('householderIdNumber')) for x in rows),
                '户列表格式异常或缺少户标识。')
        if supplement:
            require(current_total in (total, len(rows)), '补充评议分页总数与统计或本页条数不一致。')
        else:
            if total is None:
                total = current_total
            require(total == current_total, 'List changed during pagination; obtain a new stable snapshot')
        for row in rows:
            require(row['householderIdNumber'] not in seen, 'Duplicate household in snapshot')
            seen.add(row['householderIdNumber'])
        result.extend(rows)
        if len(result) >= total:
            break
        require(data['data'], 'Unexpected empty page')
    require(len(result) == total, 'Pagination count mismatch')
    require(len({x['householderIdNumber'] for x in result}) == total, 'Duplicate household in snapshot')
    if supplement:
        require(counts(client, batch, trustee) == snapshot, '补充评议分页期间户数变化，请重新查询。')
    return result


def detail(client, batch, trustee, house, state):
    rows = client.call(8, {'appraiseInfoCode': batch, 'trusteeCode': trustee,
                          'householderIdNumber': client.encrypt_house(house), 'appraiseState': state}).get('data')
    require(isinstance(rows, list), '家庭成员详情格式异常。')
    return rows


def member_plan(rows):
    require(isinstance(rows, list), '家庭成员列表格式异常。')
    result = {}
    for row in rows:
        require(isinstance(row, dict), '家庭成员条目格式异常。')
        code = row.get('appraiseResidentCode')
        require(identifier(code) and code not in result, 'Missing/duplicate member')
        items = row.get('list')
        require(isinstance(items, list) and all(isinstance(x, dict) for x in items), '评议要素列表格式异常。')
        elements = [x.get('appraiseInfoElementCode') for x in items]
        require(elements and all(identifier(x) for x in elements) and len(elements) == len(set(elements)), 'Missing/duplicate element')
        result[code] = sorted(elements)
    return result


def verify(rows, expected):
    require(rows and expected, 'Empty result cannot pass detail verification')
    require(member_plan(rows) == expected, 'Readback member/element set mismatch')
    ids = []
    values = []
    for row in rows:
        require(str(row.get('historyAppraiseData')) != '1', '历史评议结果不能作为本批次保存验收。')
        require((type(row.get('appraiseTrusteeDetailId')) is int and row['appraiseTrusteeDetailId'] > 0)
                or identifier(row.get('appraiseTrusteeDetailId')), 'Readback has no persisted detail ID')
        require(row.get('isUnderstand') is True and row.get('isSuitableCredit') is True, 'Readback member values mismatch')
        require(all(x.get('useElement') is True for x in row['list']), 'Readback element values mismatch')
        require(row.get('noSuitableCreditType') in (None, '', 'null'), 'Unexpected negative-credit reason')
        require(row.get('noSuitableCreditDesc') in (None, '', 'null'), 'Unexpected negative-credit description')
        ids.append(row['appraiseTrusteeDetailId'])
        values.append({'member': digest(row['appraiseResidentCode'])[:16], 'isUnderstand': row['isUnderstand'],
                       'isSuitableCredit': row['isSuitableCredit'], 'elementValues': [x['useElement'] for x in row['list']]})
    require(len(ids) == len(set(ids)), 'Duplicate persisted detail IDs')
    return {'members': len(rows), 'elements': sum(len(x['list']) for x in rows),
            'persistedDetailIdsDigest': digest(sorted(ids, key=lambda x: (type(x).__name__, x))),
            'memberValues': sorted(values, key=lambda x: x['member']), 'verified': True}


def validate_state(state):
    message = '续跑台账结构异常，已停止；请保留文件并联系维护人员。'
    require(isinstance(state, dict) and state.get('schemaVersion') == 2, message)
    require(all(key in state for key in ('identity', 'ruleVersion', 'batch', 'target')), message)
    require(state.get('completion') in ('pending', 'unknown', 'verified'), message)
    baseline, tasks = state.get('baselineCompleted'), state.get('tasks')
    require(isinstance(baseline, list) and all(identifier(x) for x in baseline), message)
    require(len(set(baseline)) == len(baseline), message)
    require(isinstance(tasks, list), message)
    require(bool(tasks) or (state.get('appraiseInfoType') == '4' and bool(baseline)), message)
    seen = set(baseline)
    for task in tasks:
        require(isinstance(task, dict), message)
        house, expected = task.get('house'), task.get('expected')
        require(identifier(house) and house not in seen, message)
        seen.add(house)
        require(task.get('status') in ('pending', 'unknown', 'verified'), message)
        require(isinstance(expected, dict) and bool(expected), message)
        for member, elements in expected.items():
            require(identifier(member) and isinstance(elements, list) and bool(elements)
                    and all(identifier(x) for x in elements), message)
            require(elements == sorted(set(elements)), message)
        if task['status'] == 'verified':
            require(isinstance(task.get('verification'), dict) and task['verification'].get('verified') is True, message)
    if state['completion'] != 'pending':
        require(all(t['status'] == 'verified' for t in tasks), message)


def run_selected(client, batch, target, roster_params, args, state_path, report_path=None):
    writes_before, events_before = client.writes, len(client.events)
    roster = get_roster(client, roster_params)
    require(len([x for x in roster if x['code'] == target]) == 1, '所选评议员已不在当前名单中。')
    config = client.call(9, {'code': batch}).get('data')
    require(isinstance(config, dict), '批次配置格式异常。')
    require(config.get('valid') is True and str(config.get('appraiseStatus')) == '0', '所选批次当前不可评议。')
    appraise_type = str(config.get('appraiseInfoType'))
    require(appraise_type in ('1', '2', '4') and str(config.get('markType')) == '0',
            '仅支持首轮（类型 1）、常规性复评议（类型 2）和补充评议（类型 4）的要素模式；当前类型或模式暂不执行。')
    supplement = appraise_type == '4'
    identity = {'baseUrl': client.base_url, 'enterprise': client.enterprise, 'userId': client.user_id}
    initial = {x['code']: {'status': x['selectStatus'], 'counts': counts(client, batch, x['code'])} for x in roster}
    pending = households(client, batch, target, 2, supplement=supplement)
    completed = households(client, batch, target, 1, supplement=supplement)
    pending_set = {h['householderIdNumber'] for h in pending}
    completed_set = {h['householderIdNumber'] for h in completed}
    require(not pending_set & completed_set, '同一户同时出现在已办和待办列表中。')
    require(initial[target]['counts'] == {'residentNbr': len(pending)+len(completed),
            'residentStateOneNbr': len(completed), 'residentStateTwoNbr': len(pending)}, '任务户数与列表不一致。')
    require(initial[target]['status'] in ('2', '3') and not (initial[target]['status'] == '3' and pending),
            '评议员状态与待办不一致，未自动修改。')
    public = {'target': digest(target)[:16], 'reviewers': [{'reviewer': digest(code)[:16], **v} for code, v in initial.items()],
              'targetPending': len(pending), 'targetCompleted': len(completed)}
    if not args.execute:
        for house in pending:
            rows = detail(client, batch, target, house['householderIdNumber'], 1)
            require(rows, 'Empty household detail')
            member_plan(rows)
        save(report_path.with_name('preflight.json') if report_path is not None else None, public)
        print(json.dumps(public, ensure_ascii=True))
        return public
    require(args.test_values_from_recording, '未启用已确认的测试评议规则。')
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            raise RuntimeError('续跑台账损坏，已停止；请保留文件并联系维护人员。') from None
        validate_state(state)
        require(state.get('appraiseInfoType', appraise_type if not supplement else None) == appraise_type,
                '批次类型与续跑台账不一致。')
        require(state['identity'] == identity and state['ruleVersion'] == 'taian-all-true-v1', '运行身份或评议规则与台账不一致。')
        require(state['batch'] == batch and state['target'] == target, 'Existing state belongs to another task')
        require({t['house'] for t in state['tasks']} | set(state['baselineCompleted']) == pending_set | completed_set,
                '本批次户清单已变化，与续跑台账不一致。')
        require(set(state['baselineCompleted']) <= completed_set, '历史已办户状态发生变化。')
    else:
        if not pending and initial[target]['status'] == '3':
            public.update(complete=True, contentsVerified=False, writesThisInvocation=0,
                          message='该评议员已经完成，无新增写入；未将历史数据当作本次新增验收。')
            save(report_path, public)
            print(public['message'])
            return public
        require(initial[target]['status'] == '2' and (pending or (supplement and completed)),
                '评议员状态与待办不一致，未自动修改。')
        require(initial[target]['counts']['residentNbr'] == len(pending)+len(completed), '任务总户数与列表不一致。')
        state = {'schemaVersion':2, 'identity':identity, 'ruleVersion':'taian-all-true-v1',
                 'appraiseInfoType': appraise_type,
                 'baselineCompleted':[h['householderIdNumber'] for h in completed],
                 'startedAt': datetime.now(timezone.utc).isoformat(), 'batch': batch, 'target': target,
                 'initial': initial, 'tasks': [], 'completion': 'pending',
                 'authorization': 'User confirmed all-true test values; batch and reviewer selected interactively'}
        for house in pending:
            rows = detail(client, batch, target, house['householderIdNumber'], 1)
            expected = member_plan(rows)
            require(expected, 'Empty member plan')
            state['tasks'].append({'house': house['householderIdNumber'], 'expected': expected, 'status': 'pending'})
        save(state_path, state)
    writes_this_run = 0
    for task in state['tasks']:
        house = task['house']
        existing = detail(client, batch, target, house, 2)
        if existing:
            checked = verify(existing, task['expected'])
            if task['status'] == 'verified':
                require(checked == task['verification'], '已验收明细发生变化，已停止续跑。')
            task['verification'] = checked
            task['status'] = 'verified'
            save(state_path, state)
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
        save(state_path, state)
        client.call(11, payload, write=True)
        task['verification'] = verify(detail(client, batch, target, house, 2), task['expected'])
        task['status'] = 'verified'
        save(state_path, state)
        writes_this_run += 1
        print(json.dumps({'household': digest(house)[:16], 'verifiedMembers': len(rows), 'progress': sum(t['status']=='verified' for t in state['tasks'])}), flush=True)
        if args.limit and writes_this_run >= args.limit:
            break
    all_verified = all(t['status'] == 'verified' for t in state['tasks'])
    if all_verified:
        require(not households(client, batch, target, 2, supplement=supplement), 'Pending households remain; completion forbidden')
        actual_done = households(client, batch, target, 1, supplement=supplement)
        require({h['householderIdNumber'] for h in actual_done} == {t['house'] for t in state['tasks']} | set(state['baselineCompleted']), 'Completed household set mismatch')
        require(counts(client, batch, target) == {'residentNbr':len(state['tasks'])+len(state['baselineCompleted']), 'residentStateOneNbr':len(state['tasks'])+len(state['baselineCompleted']), 'residentStateTwoNbr':0}, 'Final target counts mismatch')
        fresh = get_roster(client, roster_params)
        require({x['code'] for x in fresh} == set(initial), 'Roster changed')
        for person in fresh:
            if person['code'] != target:
                require({'status':person['selectStatus'],'counts':counts(client,batch,person['code'])} == initial[person['code']], 'Another reviewer changed')
        current = next(x for x in fresh if x['code'] == target)
        if current['selectStatus'] != '3':
            require(current['selectStatus'] == '2' and state['completion'] == 'pending', 'Unknown completion state')
            payload = dict(roster_params)
            for i, person in enumerate(fresh):
                require(identifier(person.get('idNum')) and identifier(person.get('personName')),
                        '评议员姓名或身份标识缺失，无法保存完成状态。')
                for field in ('personName','idNum','selectStatus','historyStatus','pretrialStatus'):
                    value = '3' if person['code'] == target and field == 'selectStatus' else person.get(field)
                    payload['trusteeList[%d].%s' % (i,field)] = 'null' if value is None else str(value)
            state['completion'] = 'unknown'
            save(state_path, state)
            client.call(28, payload, write=True)
        after_roster = get_roster(client, roster_params)
        require({x['code'] for x in after_roster} == set(initial), 'Roster changed after completion')
        require(next(x for x in after_roster if x['code']==target)['selectStatus']=='3', 'Completion status not persisted')
        for task in state['tasks']:
            recheck = verify(detail(client,batch,target,task['house'],2), task['expected'])
            require(recheck == task['verification'], 'Completion changed persisted detail records')
        state['completion'] = 'verified'
        save(state_path,state)
    final_roster = get_roster(client,roster_params)
    final = {x['code']:{'status':x['selectStatus'],'counts':counts(client,batch,x['code'])} for x in final_roster}
    require(set(final) == set(initial), 'Roster membership changed')
    for code in final:
        if code != target:
            require(final[code] == initial[code], 'Untargeted reviewer changed')
    result = {'verifiedAt':datetime.now(timezone.utc).isoformat(),'ruleVersion':state['ruleVersion'],
              'target':digest(target)[:16], 'complete':state['completion']=='verified',
              'householdsVerified':sum(t['status']=='verified' for t in state['tasks']),
              'membersVerified':sum(len(t['expected']) for t in state['tasks'] if t['status']=='verified'),
              'writesThisInvocation':client.writes - writes_before,
              'before':[{'reviewer':digest(k)[:16],**v} for k,v in initial.items()],
              'after':[{'reviewer':digest(k)[:16],**v} for k,v in final.items()],
              'tasks':[{'household':digest(t['house'])[:16],'status':t['status'],'verification':t.get('verification')} for t in state['tasks']],
              'untargetedReviewersUnchanged':True,'wholeBatchSubmitted':False,
              'appraiseInfoType':appraise_type, 'baselineCompletedHouseholds':len(state['baselineCompleted']),
              'limitations':['All-true element scenarios for types 1, 2 and 4 only','Baseline completed households preserved, not reappraised','No database or browser visual validation','No 1000-household or concurrent run']}
    successful_writes = client.events[events_before:]
    successful_writes = [e for e in successful_writes if e.get('write') and str(e.get('businessCode')) == '0']
    result['successfulWritesThisSession'] = len(successful_writes)
    result['successfulWriteBreakdown'] = {
        'householdSaves':sum(e['recordingTemplate']==11 for e in successful_writes),
        'reviewerCompletionSaves':sum(e['recordingTemplate']==28 for e in successful_writes)}
    save(report_path,result)
    print(json.dumps({k:result[k] for k in ('complete','householdsVerified','membersVerified','writesThisInvocation','untargetedReviewersUnchanged')},ensure_ascii=True))
    return result


