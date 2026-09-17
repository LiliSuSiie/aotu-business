# 真实进件执行

1. 复制 `../config/intake-run.example.json` 为 `../config/intake-run.local.json`，填入测试环境地址、授权令牌、产品码、已授权的测试客户明文及其对应密文。
2. 将该客户对应的两张测试证件图片放到 `../k6/fixtures/id-front.jpg`、`../k6/fixtures/id-back.jpg`。图片和私有配置均被 Git 忽略。若 OCR 挡板响应不提供 `data.idImg`，在私有配置的 `customer.idImgBase64` 填入同一张已授权测试正面图的 Base64（也不得提交）。
3. 若需自动落库核验，在私有配置的 `db` 中启用数据库，并以 `defaultsExtraFile` 指向不提交的 MySQL 连接配置。
4. 在项目根目录执行：

```powershell
.\eeds\renew-credit-automation\scripts\run-intake.ps1
```

测试环境约定已内置：验证码填写任意六位数字即可；活体接口会照真实流程调用挡板，并断言其返回了结果。脚本输出的 `reqCode` 是 `loan_apply_info`、`loan_cust_info`、`sys_file`、`sign_seal_operation_log` 的共同关联键。
