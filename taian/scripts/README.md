# 泰安评议：技术运行说明

第一次使用请先看 **[新手运行指南](../README.md)**。项目首页入口为 [README.md](../../README.md)。

## 当前入口

默认按当前使用习惯，不生成报告：

```powershell
python "E:\liwenqiu\project\aotu-business\taian\scripts\run_review.py" --no-report
```

账号配置为 `taian/config/review.private.json`（本机私有配置）。保留其中已经填写的账号，只有更换登录用户时才修改 username 和 password。不得把真实密码抄入说明文档。

流程为“配置账号密码 → 加密登录 → 终端选择批次 → 选择评议员 → 执行所选人员全部待办 → 逐户回查 → 保存完成状态 → 刷新名单”。有未完成人员时，输入 y 继续选择下一人，输入 n／q 结束；全部参与人员完成后直接退出。每次选择人员后即开始保存，只有明确选择的人员才会执行。同一进程复用登录会话和批次，下一轮菜单重新查询并只列出待评议人员。

## 启动参数

| 参数 | 行为 |
| --- | --- |
| `--no-report` | 不写报告或 HTTP 日志，仍保留恢复台账 |
| `--dry-run` | 登录及交互选择后只读检查一名评议员，不保存、不询问继续 |
| `--limit 1` | 本次最多新保存一户，仅处理一名评议员，不询问继续；下次选择相同目标可续跑 |
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

支持首轮（appraiseInfoType=1）、常规性复评议（appraiseInfoType=2）和补充评议（appraiseInfoType=4），均要求 markType=0（要素模式）、valid=true、appraiseStatus=0。类型 3（整改性复评议）及其他模式仍阻止写入；整改性复评议存在单独的评议员约束和反向评议分支，本次未启用。沿用已确认的全 true 测试值；真实差异化意见和 false 分支需要补齐输入规则与验证。

类型含义及流程依据本机 ta-service 源码中的 AppraiseInfoTypeEnum、VillageAppraiseInfoMobileController、VillageAppraiseInfoService 和 VillageAppraiseInfoResidentService 核对。详情接口的 appraiseState=1 可以返回上次评议值，只用于提取当前成员／要素；appraiseState=2 才用于当前批次已保存明细回查。因此复评议中的历史全 true 结果不会直接当成本次完成。

补充评议的已办列表和统计包含历史有效评议：整户成员已评过的户作为 baselineCompleted 保留，不要求这些户存在本批次保存明细；当前待办户仍须逐户提交并回查本批次明细。待办为 0、已办非空但人员状态为 2 时，允许建立空任务台账，经列表／统计核验后仅保存该评议员完成状态。空批次不会自动标记完成。新台账记录 appraiseInfoType，续跑时核对类型，兼容原有首轮和常规性复评议台账。

补充评议列表在后端先分页户主标识，再查询普通 List；PageInfo 可能把本页条数当作 recordsTotal。因此类型 4 使用独立统计接口的已办／待办户数作为分页目标，并在分页前后检查统计稳定、户标识唯一、数量一致；只接受 recordsTotal 为统计总数或当前页条数。缺页、重复页、统计冲突会停止，不会少取一页就保存或宣称完成。类型 1／2 仍使用原分页总数校验。

台账按服务地址、企业、批次、登录用户和评议员隔离，路径明确传给执行器，不依赖模块全局变量。同批次使用本机锁串行处理；每名评议员回查和保存完成后释放锁，再等待交互。state/interactive 中的台账含敏感业务关联信息，不应分享或随意删除。已有锁不会自动删除或抢占。

写入前先记结果未知；请求失败不盲重试。再次选择同一目标时先读取已办明细，结果一致才能跳过已保存户并继续。未知写入或冲突不能通过删除台账绕过。

程序使用固定待办快照、逐户详情回查和最终集合／统计核验。已有历史完成户保留，不计成本次新增。任务全部通过后才设置所选评议员完成状态。

接口返回结构、非负户数及总数关系、名单唯一性、成员和要素唯一性、台账结构及续跑户集合均有校验。已验收明细发生变化时停止，不覆盖原验收记录。任一人员失败后停止本次运行，保留进度，不跳到下一人。无报告模式保留同样的续跑检查；启用报告时，reviewers 子目录分别保存每名人员的结果，写入计数按人员单独统计，result.json 保留最近一人的结果。

## 验证与依赖

依赖 Python 3 和 PyCryptodome。当前这台电脑已有运行环境，正常使用不必重复安装。其他机器的依赖清单为 [requirements.txt](../requirements.txt)。

离线 HTTP 集成测试覆盖首轮执行、常规性复评议历史值、补充评议跨页查询／历史已办保留／仅保存完成状态、多名评议员连续选择、全部完成自动退出、主动结束、输入结束、限量／只读模式、不生成报告、异常返回、损坏台账、运行锁、保存及完成请求失败后的回查恢复。测试只连接本机模拟服务，不登录或修改真实业务系统。

此前真实测试环境无报告执行完成过 bb03 的 7 户、10 名成员，逐户回查及完成状态检查通过；这是历史执行记录，不代表当前名单状态。新增的复评议、补充评议与连续选择已纳入离线验证，尚未对当前真实批次执行写入验收。

在项目根目录运行离线测试：

```powershell
python -m unittest discover -s taian\tests -v
```

1000 户实际运行、多机并发、类型 3 和评分模式仍未完成验收。旧 reports 下的四户试验及模拟接口记录保留为历史证据，不应把其中“当时密码为空、尚未真实登录”等阶段性描述当作当前状态。
