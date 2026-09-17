# 续授信自动化测试包

本目录是独立于 `mcwp-service` 的测试资产，**不会修改服务代码、配置或测试数据**。

## 适用版本

- 代码基线：`mcwp-service` 的 `eeds_zcsx_master` 分支（已核实）。
- 需求基线：同级目录的《续授信需求.txt》《技术方案.txt》。

现状代码已有续授信客户跑批、文件生成、数据更新、客户列表和客户经理确认；没有发现专门的续授信自动化测试。

## 内容

- [测试策略与范围](TEST_STRATEGY.md)
- [初始需求测试用例](testcases/01-initial-requirement.md)
- [优化需求测试用例](testcases/02-optimization.md)
- [可清理的关联测试数据](test-data/README.md)
- [k6 冒烟脚本](k6/renew-credit-api.js)

## 接入方式

1. 在测试环境准备专用企业、两名客户经理和可回滚的测试数据；不得使用生产数据。
2. 使用浏览器抓包或 Swagger 确认认证 Header 名称与接口返回码格式。当前脚本优先使用 `TOKEN`，不保存账号、密码或密钥。
3. 先运行只读列表冒烟：

```powershell
k6 run -e BASE_URL=https://test.example.com -e TOKEN=*** .\k6\renew-credit-api.js
```

4. 确认接口会改变客户确认状态，只有在隔离数据下并显式传入 `CONFIRM_ID` 时才执行。

```powershell
k6 run -e BASE_URL=https://test.example.com -e TOKEN=*** -e CONFIRM_ID=123 .\k6\renew-credit-api.js
```

定时任务、文件上传、征信及模型调用均有外部副作用，不纳入默认脚本；按用例中的前置数据、SQL 断言及人工审批在测试环境执行。
