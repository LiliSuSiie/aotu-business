-- 续授信初始需求测试数据（MySQL 5.6+）
-- 仅在通过 01-precheck.sql 的隔离测试库执行。
-- 注意：本脚本使用显式进件 ID，使 oldlcno 第 15 位起可准确关联到 loan_apply_info.id。

SET @batch_date := '2026-09-01';
SET @enterprise_code := 'ATRC_EEDS';
SET @belong_user_id := 900001;
SET @belong_dept_id := 900001;
SET @village_id := 900001;

-- 一、核心客户：合同 customerid -> MF_CUSTOMER_ID。
INSERT INTO eedsxd_customer_info
  (batch_date, customer_id, customer_name, cert_type, cert_id, mf_customer_id, status, create_date, update_date, isdel)
VALUES
  (@batch_date, 'ATRC_CUST_001', 'ATRC_25岁边界', '01', '110101200109010012', 'ATRC_CORE_001', 'NORMAL', NOW(), NOW(), '0'),
  (@batch_date, 'ATRC_CUST_002', 'ATRC_64岁边界', '01', '110101196209010029', 'ATRC_CORE_002', 'NORMAL', NOW(), NOW(), '0'),
  (@batch_date, 'ATRC_CUST_003', 'ATRC_24岁下限外', '01', '110101200209010036', 'ATRC_CORE_003', 'NORMAL', NOW(), NOW(), '0'),
  (@batch_date, 'ATRC_CUST_004', 'ATRC_65岁上限外', '01', '110101196108310049', 'ATRC_CORE_004', 'NORMAL', NOW(), NOW(), '0'),
  (@batch_date, 'ATRC_CUST_005', 'ATRC_白名单无效', '01', '110101198001010053', 'ATRC_CORE_005', 'NORMAL', NOW(), NOW(), '0'),
  (@batch_date, 'ATRC_CUST_006', 'ATRC_到期91天', '01', '110101197001010067', 'ATRC_CORE_006', 'NORMAL', NOW(), NOW(), '0'),
  (@batch_date, 'ATRC_CUST_007', 'ATRC_历史续授信', '01', '110101198001010053', 'ATRC_CORE_007', 'NORMAL', NOW(), NOW(), '0');

-- 二、原始首贷/历史续授信进件：合同 oldlcno 前 14 位为占位符，后半段为进件 ID。
INSERT INTO loan_apply_info
  (id, code, enterprise_code, cust_name, id_card_no, village_id, belong_user_id, belong_dept_id,
   apply_state_code, apply_date, apply_amount, apply_period, loan_type, isdel, creator, updator, create_date, update_date)
VALUES
  (900001001, 'ATRC_LOAN_001', @enterprise_code, 'ATRC_25岁边界', '110101200109010012', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '1', 0, 0, 0, NOW(), NOW()),
  (900001002, 'ATRC_LOAN_002', @enterprise_code, 'ATRC_64岁边界', '110101196209010029', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '1', 0, 0, 0, NOW(), NOW()),
  (900001003, 'ATRC_LOAN_003', @enterprise_code, 'ATRC_24岁下限外', '110101200209010036', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '1', 0, 0, 0, NOW(), NOW()),
  (900001004, 'ATRC_LOAN_004', @enterprise_code, 'ATRC_65岁上限外', '110101196108310049', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '1', 0, 0, 0, NOW(), NOW()),
  (900001005, 'ATRC_LOAN_005', @enterprise_code, 'ATRC_白名单无效', '110101198001010053', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '1', 0, 0, 0, NOW(), NOW()),
  (900001006, 'ATRC_LOAN_006', @enterprise_code, 'ATRC_到期91天', '110101197001010067', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '1', 0, 0, 0, NOW(), NOW()),
  (900001007, 'ATRC_LOAN_007', @enterprise_code, 'ATRC_历史续授信', '110101198001010053', @village_id, @belong_user_id, @belong_dept_id, '7', NOW(), 100000.00, 12, '2', 0, 0, 0, NOW(), NOW());

-- 三、白名单：001/002/003/004 可用于年龄规则；005 为无效；006 为到期窗口排除；007 用于 loan_type=2 排除。
INSERT INTO customer_white_list
  (code, customer_name, id_number, village_id, account_manager_code, belong_dept_id,
   credit_amount, annual_interest_year_rate, credit_start_date, credit_date_end, belong_user_id,
   enterprise_code, isvalid, creater, updater, create_time, update_time, isdel, invalid_reason)
VALUES
  ('ATRC_WL_001', 'ATRC_25岁边界', '110101200109010012', @village_id, 'ATRC_AM', @belong_dept_id, 100000.00, 0.050000, NOW(), '2030-12-31', @belong_user_id, @enterprise_code, 1, 0, 0, NOW(), NOW(), 0, NULL),
  ('ATRC_WL_002', 'ATRC_64岁边界', '110101196209010029', @village_id, 'ATRC_AM', @belong_dept_id, 100000.00, 0.050000, NOW(), '2030-12-31', @belong_user_id, @enterprise_code, 1, 0, 0, NOW(), NOW(), 0, NULL),
  ('ATRC_WL_003', 'ATRC_24岁下限外', '110101200209010036', @village_id, 'ATRC_AM', @belong_dept_id, 100000.00, 0.050000, NOW(), '2030-12-31', @belong_user_id, @enterprise_code, 1, 0, 0, NOW(), NOW(), 0, NULL),
  ('ATRC_WL_004', 'ATRC_65岁上限外', '110101196108310049', @village_id, 'ATRC_AM', @belong_dept_id, 100000.00, 0.050000, NOW(), '2030-12-31', @belong_user_id, @enterprise_code, 1, 0, 0, NOW(), NOW(), 0, NULL),
  ('ATRC_WL_005', 'ATRC_白名单无效', '110101198001010053', @village_id, 'ATRC_AM', @belong_dept_id, 100000.00, 0.050000, NOW(), '2030-12-31', @belong_user_id, @enterprise_code, 0, 0, 0, NOW(), NOW(), 0, 'ATRC_TEST_INVALID'),
  ('ATRC_WL_006', 'ATRC_到期91天', '110101197001010067', @village_id, 'ATRC_AM', @belong_dept_id, 100000.00, 0.050000, NOW(), '2030-12-31', @belong_user_id, @enterprise_code, 1, 0, 0, NOW(), NOW(), 0, NULL);

-- 四、合同。maturity 以 @batch_date 为基准覆盖当日、+90、+91；oldlcno 的第 15 位起是上述进件 ID。
INSERT INTO eedsxd_business_contract
  (task_batch_date, serialno, oldlcno, customerid, maturity, status, isdel, create_date)
VALUES
  (@batch_date, 'ATRC_CONTRACT_001', 'ATRC_PREFIX000900001001', 'ATRC_CUST_001', @batch_date, 'EFFECTIVE', 0, NOW()),
  (@batch_date, 'ATRC_CONTRACT_002', 'ATRC_PREFIX000900001002', 'ATRC_CUST_002', DATE_ADD(@batch_date, INTERVAL 90 DAY), 'EFFECTIVE', 0, NOW()),
  (@batch_date, 'ATRC_CONTRACT_003', 'ATRC_PREFIX000900001003', 'ATRC_CUST_003', DATE_ADD(@batch_date, INTERVAL 30 DAY), 'EFFECTIVE', 0, NOW()),
  (@batch_date, 'ATRC_CONTRACT_004', 'ATRC_PREFIX000900001004', 'ATRC_CUST_004', DATE_ADD(@batch_date, INTERVAL 30 DAY), 'EFFECTIVE', 0, NOW()),
  (@batch_date, 'ATRC_CONTRACT_005', 'ATRC_PREFIX000900001005', 'ATRC_CUST_005', DATE_ADD(@batch_date, INTERVAL 30 DAY), 'EFFECTIVE', 0, NOW()),
  (@batch_date, 'ATRC_CONTRACT_006', 'ATRC_PREFIX000900001006', 'ATRC_CUST_006', DATE_ADD(@batch_date, INTERVAL 91 DAY), 'EFFECTIVE', 0, NOW()),
  (@batch_date, 'ATRC_CONTRACT_007', 'ATRC_PREFIX000900001007', 'ATRC_CUST_007', DATE_ADD(@batch_date, INTERVAL 30 DAY), 'EFFECTIVE', 0, NOW());

-- 导入后必须先运行 03-verify.sql；通过后才能触发跑批。
