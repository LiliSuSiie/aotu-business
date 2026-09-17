# 泰安评议：技术运行说明

第一次使用请先看 **[新手运行指南](../README.md)**。项目首页入口为 [README.md](../../README.md)。

## 当前入口

默认按当前使用习惯，不生成报告：

```powershell
python "E:\liwenqiu\project\aotu-business\taian\scripts\run_review.py" --no-report
```

账号配置为 `taian/config/review.private.json`（本机私有配置）。保留其中已经填写的账号，只有更换登录用户时才修改 username 和 password。不得把真实密码抄入说明文档。

流程为“配置账号密码 → 加密登录 → 终端选择批次 → 选择评议员 → 执行所选人员全部待办 → 逐户回查 → 保存完成状态”。第二次选择后即开始保存，每次只处理一名评议员，不会自动处理全批次所有人员。

## 启动参数

| 参数 | 行为 |
| --- | --- |
| `--no-report` | 不写报告或 HTTP 日志，仍保留恢复台账 |
| `--dry-run` | 登录及交互选择后只读检查，不保存评议 |
| `--limit 1` | 本次最多新保存一户，下次选择相同目标可继续 |
| `--config "完整配置路径"` | 使用指定的本地账号配置 |
| 不带参数 | 交互选择后执行，并生成报告 |

只读预检：

```powershell
python "E:\liwenqiu\project\aotu-business\taian\scripts\run_review.py" --dry-run --no-report
```

先处理一户：

```powershell
python "E:\liwenqiu\project\aotu-business\taian\scripts\run_review.py" --limit 1 --no-report
```

旧入口 run_single_review.py 转接同一流程。run-review.ps1 也可使用，但当前包装脚本只提供 DryRun 和 Limit 参数，会沿用生成报告的行为；需要不生成报告时使用上面的 Python 命令。

## 登录与查询契约

用户名、密码及户主证件号查询使用 AES-ECB、PKCS7 填充、Hex 输出，密钥为用户指定的协议常量。启动自检验证 `hh01 → c4d94d84638ff343fbc6aa700906a5e6`，不依赖其他前端工程或 T.json。

登录路径 `/comm/v1/user/login`，loginType=4、smsType=H5。使用本次响应 data.token、data.enterpCode 和 data.userId 建立会话；Token 仅存内存，不打印或写入审计。登录失败或缺少有效身份时停止，不回退旧 Token。

部分环境可能额外校验短信，配置可增加有效 smsVerifyCode。程序不会自动发短信或绕过校验；会话中途失效时停止，由下次启动重新登录并回查进度。

批次列表支持分页，兼容服务端 recordsTotal=0 但当前页仍非空的情况。终端支持序号或完整 code，非法输入重新提示；q／EOF 不自动选第一项。

当前参与名单查询和完成保存按 appraiseInfoCode 解析关联。列表明确返回 villageCode 时传入；不把 villageId 冒充村码，不复制其他批次参数。

## 规则与恢复

当前仅启用首轮、要素模式（appraiseInfoType=1、markType=0），沿用已确认的全 true 测试值。真实差异化评议结果、其他类型和 false 分支需要补齐业务输入与验证。

台账按服务地址、企业、批次、登录用户和评议员隔离，同批次使用本机锁串行处理。state/interactive 中的台账含敏感业务关联信息，不应分享或随意删除。

写入前先记结果未知；请求失败不盲重试。再次选择同一目标时先读取已办明细，结果一致才能跳过已保存户并继续。未知写入或冲突不能通过删除台账绕过。

程序使用固定待办快照、逐户详情回查和最终集合／统计核验。已有历史完成户保留，不计成本次新增。任务全部通过后才设置所选评议员完成状态。

## 验证与依赖

依赖 Python 3 和 PyCryptodome。当前这台电脑已有运行环境，正常使用不必重复安装。其他机器的依赖清单为 [requirements.txt](../requirements.txt)。

已完成 9 项离线 HTTP 集成测试，并已使用私有配置中的实际账号成功登录、选择批次和人员、完成真实测试环境评议。最近一次无报告执行完成 bb03 的 7 户、10 名成员，逐户回查及完成状态检查通过；该结论是历史执行记录，不代表当前名单状态。

在项目根目录运行离线测试：

```powershell
python -m unittest discover -s taian\tests -v
```

1000 户实际运行、多机并发和其他评议类型仍未完成验收。旧 reports 下的四户试验及模拟接口记录保留为历史证据，不应把其中“当时密码为空、尚未真实登录”等阶段性描述当作当前状态。
