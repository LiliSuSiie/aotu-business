-- 续授信测试数据：执行前检查（MySQL）
-- 只读。请在隔离测试库执行。

SET @seed_prefix := 'ATRC_';

-- 1) 这些查询都应返回 0；否则先执行 99-cleanup.sql 或更换测试库。
SELECT 'loan_apply_info' AS table_name, COUNT(*) AS conflicts
FROM loan_apply_info WHERE code LIKE CONCAT(@seed_prefix, '%')
UNION ALL
SELECT 'eedsxd_customer_info', COUNT(*)
FROM eedsxd_customer_info WHERE customer_id LIKE CONCAT(@seed_prefix, '%')
UNION ALL
SELECT 'customer_white_list', COUNT(*)
FROM customer_white_list WHERE code LIKE CONCAT(@seed_prefix, '%')
UNION ALL
SELECT 'eedsxd_business_contract', COUNT(*)
FROM eedsxd_business_contract WHERE serialno LIKE CONCAT(@seed_prefix, '%');

-- 2) 需求链路的最小表/字段检查。任何一项不存在时停止，不要执行种子脚本。
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND (
    (table_name = 'eedsxd_business_contract' AND column_name IN ('customerid','oldlcno','serialno','maturity','status','isdel')) OR
    (table_name = 'eedsxd_customer_info' AND column_name IN ('customer_id','mf_customer_id','isdel')) OR
    (table_name = 'loan_apply_info' AND column_name IN ('id','code','id_card_no','loan_type','isdel')) OR
    (table_name = 'customer_white_list' AND column_name IN ('code','id_number','isvalid','credit_date_end','isdel')) OR
    (table_name = 'renew_credit_customer' AND column_name IN ('loan_id','id_number','contract_no','customer_status'))
  )
ORDER BY table_name, column_name;

-- 3) 执行前记录基线，便于归因。
SELECT NOW() AS checked_at, DATABASE() AS database_name, @@hostname AS db_host;
