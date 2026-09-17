"""登录 → 终端选择批次 → 选择评议员 → 自动评议及回查。"""
import argparse
import os
from pathlib import Path
import sys
import uuid

import review_core as core
from review_client import Client, batch_list, choose, load_config

ROOT = Path(__file__).resolve().parents[1]
STATUS = {'1': '未选择', '2': '待评议', '3': '已完成'}


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
                           x.get('appraiseInfoTypeText') or x.get('appraiseInfoType') or '未知'), input_fn, output)
    batch = batch_row['code']
    # These two controllers resolve all associations from appraiseInfoCode.
    # Never substitute villageId for villageCode or copy another batch's village.
    roster_params = {'appraiseInfoCode': batch}
    if batch_row.get('villageCode'):
        roster_params['villageCode'] = batch_row['villageCode']
    roster = client.call(29, roster_params).get('data')
    if not isinstance(roster, list):
        raise RuntimeError('评议员列表格式异常。')
    if len({x.get('code') for x in roster}) != len(roster) or any(not x.get('code') for x in roster):
        raise RuntimeError('评议员列表包含缺失或重复 code。')
    for person in roster:
        person['_counts'] = core.counts(client, batch, person['code'])
    selected = choose('选择本批次评议员', roster,
                      lambda x: '%s | code=%s | %s | 已办=%s 待办=%s' % (
                          x.get('personName') or '未命名评议员', x['code'],
                          STATUS.get(str(x.get('selectStatus')), '未知状态'),
                          x['_counts']['residentStateOneNbr'], x['_counts']['residentStateTwoNbr']), input_fn, output)
    target = selected['code']
    if str(selected.get('selectStatus')) not in ('2', '3'):
        raise RuntimeError('此人员未处于待评议或已完成状态，未自动调整参与名单。')
    output('\n已选择批次 %s，评议员 %s；待办 %s 户。' % (
        batch, selected.get('personName') or target, selected['_counts']['residentStateTwoNbr']))
    output('模式：%s；测试取值：是否了解、是否适宜授信、全部要素均为 true。' % (
        '只读预检' if args.dry_run else '自动评议'))
    # Serialize by environment + enterprise + batch, even across login accounts.
    scope = core.digest([client.base_url, client.enterprise, batch])[:32]
    owner = core.digest([client.user_id, target])[:32]
    state_dir = root / 'state' / 'interactive' / scope
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / 'batch.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('这个批次已有运行锁；请先核对原进程，不要删除进度台账。') from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        core.STATE = state_dir / (owner + '.json')
        core.REPORT = None if no_report else folder / 'result.json'
        core.AUDIT = client.audit
        args.execute = not args.dry_run
        args.test_values_from_recording = True
        core.run_selected(client, batch, target, roster_params, args)
        output('运行结束，未生成报告。' if no_report else '运行结束，结果保存在：%s' % folder)
        return folder
    except Exception as exc:
        core.save(None if no_report else folder / 'failure.json', {'errorType': type(exc).__name__,
                  'writesThisInvocation': client.writes, 'complete': False,
                  'nextStep': '保留台账，核对审计；同一目标再次运行会先回查已保存数据。'})
        raise
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config' / 'review.private.json', help='账号配置文件')
    parser.add_argument('--dry-run', action='store_true', help='登录和交互选择后，只读预检，不保存评议')
    parser.add_argument('--no-report', action='store_true', help='不生成报告或 HTTP 日志，仅保留续跑台账')
    parser.add_argument('--limit', type=int, default=0, help='本次最多保存几户；0 表示所选人员全部待办')
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
        print(str(exc) if isinstance(exc, RuntimeError) else '运行失败（%s），请查看本次报告。' % type(exc).__name__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
