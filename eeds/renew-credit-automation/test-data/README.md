# 续授信测试数据

本目录提供**仅供隔离测试库执行**的 MySQL 测试数据。脚本不包含生产连接信息，也不会自动执行。

执行顺序：

1. `01-precheck.sql`：确认目标库无同名测试数据，且具备需求中的基础表。
2. `02-seed-initial.sql`：写入初始需求的候选合同、核心客户、首贷进件与白名单。
3. 手动触发目标日期的 `renew/doData` 任务，使用模型/征信测试桩控制返回值。
4. `03-verify.sql`：确认合同到进件、白名单和续授信客户的关联完整。
5. 测试结束执行 `99-cleanup.sql`。

## 固定数据命名

- 测试前缀：`ATRC_`（Aotu Test Renew Credit）。
- 测试批次日期：`2026-09-01`。执行跑批时应传同一日期；年龄边界数据以此日期生成。
- 测试进件 ID：`900001001` 至 `900001007`。
- 固定身份证均为合法 18 位校验码；含 25、64、24、65 周岁边界。

## 关系链

```text
EEDSXD_BUSINESS_CONTRACT.customerid
  -> eedsxd_customer_info.customer_id
  -> eedsxd_customer_info.mf_customer_id

EEDSXD_BUSINESS_CONTRACT.oldlcno[第15位起]
  -> loan_apply_info.id
  -> loan_apply_info.id_card_no
  -> customer_white_list.id_number
  -> 跑批生成 renew_credit_customer
```

`renew_credit_customer`、`batch_task_log`、模型记录都由被测跑批生成，种子脚本不预写这些结果表，以免把待验证结果伪造成已通过。

## 优化版说明

技术方案中的 `renew_credit_customer_batch` 在当前 `eeds_zcsx_master` 基线没有实现。优化功能合入并提供最终 DDL 后，再依据 [优化用例](../testcases/02-optimization.md) 为每个客户创建批次调用记录；不得在当前库手工创建同名表来伪造实现。
