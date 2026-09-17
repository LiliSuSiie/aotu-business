-- 由 scripts/run-intake.ps1 在内存中替换占位符后执行。
-- 不回显姓名、身份证或手机号；仅返回匹配结论和脱敏业务码。
SET @req_code = '{{REQ_CODE}}';
SET @expected_name = '{{CUSTOMER_NAME}}';
SET @expected_id_card = '{{ID_CARD_NO}}';
SET @expected_phone = '{{PHONE_NUMBER}}';

SELECT
  'loan_apply_info' AS assertion_name,
  CASE
    WHEN COUNT(*) = 1
     AND SUM(CUST_NAME <=> @expected_name) = 1
     AND SUM(ID_CARD_NO <=> @expected_id_card) = 1
     AND SUM(PHONE_NUMBER <=> @expected_phone) = 1
    THEN 'PASS' ELSE 'FAIL'
  END AS result,
  COUNT(*) AS row_count,
  MAX(APPLY_STATE_CODE) AS apply_state_code
FROM loan_apply_info
WHERE CODE = @req_code AND (ISDEL = 0 OR ISDEL IS NULL);

SELECT
  'loan_cust_info' AS assertion_name,
  CASE
    WHEN COUNT(*) >= 1
     AND SUM(CUST_NAME <=> @expected_name) >= 1
     AND SUM(ID_NUMBER <=> @expected_id_card) >= 1
     AND SUM(TELPHONE <=> @expected_phone) >= 1
    THEN 'PASS' ELSE 'FAIL'
  END AS result,
  COUNT(*) AS row_count
FROM loan_cust_info
WHERE CODE = @req_code AND (ISDEL = 0 OR ISDEL IS NULL);

SELECT
  'sys_file' AS assertion_name,
  CASE WHEN COUNT(DISTINCT BIZ_TYPE) >= 2 THEN 'PASS' ELSE 'FAIL' END AS result,
  COUNT(*) AS row_count,
  GROUP_CONCAT(DISTINCT BIZ_TYPE ORDER BY BIZ_TYPE SEPARATOR ',') AS file_types
FROM sys_file
WHERE BIZ_CODE = @req_code AND (ISDEL = 0 OR ISDEL IS NULL);

SELECT
  'sign_seal_operation_log' AS assertion_name,
  CASE WHEN COUNT(DISTINCT BIZ_NODE_TYPE) >= 4 THEN 'PASS' ELSE 'FAIL' END AS result,
  COUNT(*) AS row_count,
  GROUP_CONCAT(DISTINCT BIZ_NODE_TYPE ORDER BY BIZ_NODE_TYPE SEPARATOR ',') AS sign_nodes
FROM sign_seal_operation_log
WHERE BIZ_CODE = @req_code;
