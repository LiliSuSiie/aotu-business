-- 续授信测试数据：导入后关系校验（只读）
SET @batch_date := '2026-09-01';

-- 每份合同应解析到预期进件、核心客户和白名单。006/007 虽可关联，业务上应在后续规则中排除。
SELECT
  c.serialno,
  c.status,
  c.maturity,
  c.customerid,
  SUBSTRING(c.oldlcno, 15) AS parsed_loan_id,
  ci.mf_customer_id,
  lai.id AS loan_id,
  lai.loan_type,
  lai.id_card_no,
  cwl.isvalid AS white_list_valid,
  cwl.credit_date_end
FROM eedsxd_business_contract c
LEFT JOIN eedsxd_customer_info ci ON ci.customer_id = c.customerid AND ci.isdel = '0'
LEFT JOIN loan_apply_info lai ON lai.id = CAST(SUBSTRING(c.oldlcno, 15) AS UNSIGNED) AND lai.isdel = 0
LEFT JOIN customer_white_list cwl ON cwl.id_number = lai.id_card_no AND cwl.isdel = 0
WHERE c.serialno LIKE 'ATRC_CONTRACT_%'
ORDER BY c.serialno;

-- 业务预期：001/002 可进入模型；003/004/005 会生成客户但在基础规则拦截；006/007 不应生成续授信客户。
SELECT
  contract_no, loan_id, id_number, customer_status, customer_status_desc,
  manager_confirm, batch_date, batch_no, credit_customer_id, core_customer_id
FROM renew_credit_customer
WHERE contract_no LIKE 'ATRC_CONTRACT_%'
ORDER BY contract_no;

-- 目标批次的任务状态；同一 task_type + batch_date 只能一条。
SELECT task_type, batch_date, status, code, create_date, update_date
FROM batch_task_log
WHERE batch_date = @batch_date
  AND task_type IN ('doData', 'doFile', 'updateData')
ORDER BY task_type, id;
