-- 续授信测试数据清理（MySQL）
-- 仅删除本测试包 ATRC_ 前缀创建的数据及由其合同产生的续授信记录。
-- 先在测试环境审核 SELECT 结果，再执行 DELETE。

-- 预览删除范围
SELECT * FROM renew_credit_customer WHERE contract_no LIKE 'ATRC_CONTRACT_%';
SELECT * FROM batch_task_log WHERE batch_date = '2026-09-01' AND code LIKE 'xsx%';

-- 由被测任务生成的结果先删，避免外键或唯一键影响重新导入。
DELETE FROM renew_credit_customer WHERE contract_no LIKE 'ATRC_CONTRACT_%';

-- 只清理由测试批次产生的续授信任务日志；若目标日期同时被真实测试使用，请改用专用日期后再执行。
DELETE FROM batch_task_log
WHERE batch_date = '2026-09-01'
  AND task_type IN ('doData', 'doFile', 'updateData');

DELETE FROM eedsxd_business_contract WHERE serialno LIKE 'ATRC_CONTRACT_%';
DELETE FROM customer_white_list WHERE code LIKE 'ATRC_WL_%';
DELETE FROM loan_apply_info WHERE code LIKE 'ATRC_LOAN_%';
DELETE FROM eedsxd_customer_info WHERE customer_id LIKE 'ATRC_CUST_%';
