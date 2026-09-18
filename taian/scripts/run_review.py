"""登录 → 终端选择批次 → 选择评议员 → 自动评议及回查。"""
import argparse
import os
from pathlib import Path
import sys
import uuid

import review_core as core
from review_client import Client, ask_continue, batch_list, choose, load_config

ROOT = Path(__file__).resolve().parents[1]
STATUS = {'1': '未选择', '2': '待评议', '3': '已完成'}
APPRAISE_TYPES = {'1': '首轮评议', '2': '常规性复评议', '3': '整改性复评议', '4': '补充评议'}


def batch_type_label(row):
    code = str(row.get('appraiseInfoType') or '')
    name = APPRAISE_TYPES.get(code) or row.get('appraiseInfoTypeText')
    return '%s（%s）' % (code, name) if code and name else code or name or '未知'


def refresh_roster(client, batch, params):
    roster = core.get_roster(client, params)
    for person in roster:
        person['_counts'] = core.counts(client, batch, person['code'])
        core.require(not (person['selectStatus'] == '3' and person['_counts']['residentStateTwoNbr']),
                     '评议员已完成状态与待办数冲突，请核对业务数据。')
    return roster


def all_complete(roster):
    participants = [p for p in roster if p['selectStatus'] in ('2', '3')]
    return bool(participants) and all(p['selectStatus'] == '3' for p in participants)


def execute_selected(client, batch, target, params, args, state_dir, report):
    # One batch lock spans verification and writes, then releases before waiting for input.
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / 'batch.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('这个批次已有运行锁；请先核对原进程，不要删除进度台账。') from None
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(str(os.getpid()))
        owner = core.digest([client.user_id, target])[:32]
        return core.run_selected(client, batch, target, params, args,
                                 state_path=state_dir / (owner + '.json'), report_path=report)
    finally:
        lock.unlink(missing_ok=True)


def run_workflow(args, input_fn=input, output=print, root=ROOT):
    config = load_config(args.config)
    session = uuid.uuid4().hex
    folder = root / 'reports' / 'interactive' / session
    no_report = getattr(args, 'no_report', False)
    client = Client(config, None if no_report else folder / 'http.jsonl')
    output('正在登录……')
    client.login()
    output('登录成功，已获取本次会话。')
    if not no_report:
        output('本次报告目录：%s' % folder)
    batches = batch_list(client)
    batch_row = choose('选择评议批次', batches,
                       lambda x: '%s | code=%s | 状态=%s | 类型=%s' % (
                           x.get('villageName') or '未命名批次', x['code'], x.get('appraiseStatus'),
                           batch_type_label(x)), input_fn, output)
    batch = batch_row['code']
    # These two controllers resolve all associations from appraiseInfoCode.
    # Never substitute villageId for villageCode or copy another batch's village.
    roster_params = {'appraiseInfoCode': batch}
    if batch_row.get('villageCode'):
        roster_params['villageCode'] = batch_row['villageCode']
    scope = core.digest([client.base_url, client.enterprise, batch])[:32]
    state_dir = root / 'state' / 'interactive' / scope
    report = None if no_report else folder / 'result.json'
    args.execute = not args.dry_run
    args.test_values_from_recording = True
    first = True
    try:
        while True:
            roster = refresh_roster(client, batch, roster_params)
            if all_complete(roster):
                output('本批次所有参与评议的人员均已完成，无需继续选择。')
                if first:
                    core.save(report, {'complete': True, 'contentsVerified': False, 'writesThisInvocation': 0,
                                       'message': '按当前名单和统计判断已完成，本次未逐户验收历史结果。'})
                break
            choices = roster if first else [p for p in roster if p['selectStatus'] == '2']
            selected = choose('选择本批次评议员', choices,
                              lambda x: '%s | code=%s | %s | 已办=%s 待办=%s' % (
                                  x.get('personName') or '未命名评议员', x['code'], STATUS[x['selectStatus']],
                                  x['_counts']['residentStateOneNbr'], x['_counts']['residentStateTwoNbr']), input_fn, output)
            target = selected['code']
            core.require(selected['selectStatus'] in ('2', '3'),
                         '此人员未处于待评议或已完成状态，未自动调整参与名单。')
            output('\n已选择批次 %s，评议员 %s；待办 %s 户。' % (
                batch, selected.get('personName') or target, selected['_counts']['residentStateTwoNbr']))
            output('模式：%s；测试取值：是否了解、是否适宜授信、全部要素均为 true。' % (
                '只读预检' if args.dry_run else '自动评议'))
            result = execute_selected(client, batch, target, roster_params, args, state_dir, report)
            if args.dry_run:
                output('所选评议员只读预检结束，未保存评议。')
                break
            if not no_report:
                core.save(folder / 'reviewers' / (core.digest(target)[:32] + '.json'), result)
            if not result['complete']:
                output('所选评议员尚未全部完成，已保留进度；再次选择同一人员可续跑。')
                break
            output('评议员 %s 已完成，正在刷新名单。' % (selected.get('personName') or target))
            roster = refresh_roster(client, batch, roster_params)
            if all_complete(roster):
                output('本批次所有参与评议的人员均已完成，无需继续选择。')
                break
            remaining = sum(p['selectStatus'] == '2' for p in roster)
            output('本批次还有 %s 名评议员未完成。' % remaining)
            if args.limit:
                output('本次为限量运行，保留进度后结束；正常连续评议请去掉 --limit。')
                break
            if not ask_continue(input_fn, output):
                output('已结束本次运行，剩余人员可下次继续选择。')
                break
            first = False
    except Exception as exc:
        core.save(None if no_report else folder / 'failure.json', {'errorType': type(exc).__name__,
                  'writesThisInvocation': client.writes, 'complete': False,
                  'nextStep': '保留台账，核对审计；同一目标再次运行会先回查已保存数据。'})
        raise
    output('运行结束，未生成报告。' if no_report else '运行结束，结果保存在：%s' % folder)
    return folder


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config' / 'review.private.json', help='账号配置文件')
    parser.add_argument('--dry-run', action='store_true', help='登录和交互选择后，只读预检，不保存评议')
    parser.add_argument('--no-report', action='store_true', help='不生成报告或 HTTP 日志，仅保留续跑台账')
    parser.add_argument('--limit', type=int, default=0, help='本次最多新保存几户；大于 0 时只处理一名评议员，0 不限')
    # Keep historical command flags compatible; neither can supply a token/target.
    parser.add_argument('--execute', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--test-values-from-recording', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error('--limit 不能为负数')
    try:
        run_workflow(args)
        return 0
    except KeyboardInterrupt:
        print('\n已退出；如执行中中断，保留台账，下次选择同一目标先回查。')
        return 130
    except Exception as exc:
        # Do not echo arbitrary exceptions that may contain form values or URLs.
        print(str(exc) if isinstance(exc, RuntimeError) else '运行失败（%s），请保留终端提示和续跑台账，联系维护人员。' % type(exc).__name__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
