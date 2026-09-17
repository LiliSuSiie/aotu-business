# 进件接口自动化测试包

本目录由 [`../进件.json`](../进件.json) 的录制请求生成，独立于续授信自动化资产，也不会修改 `mcwp-service`。

## 资产说明

- [接口自动化方案](recordings/进件-接口自动化方案.md)：请求顺序、`reqCode` 数据关联、覆盖范围与风险。
- [k6 主流程](k6/intake-application-flow.js)：真实上传、OCR、授权、短信、活体与进件提交。
- [私有配置模板](config/intake-run.example.json)：测试环境 URL、令牌、授权测试客户及其密文。
- [运行说明](scripts/README.md)：一键执行、图片准备和数据库核验。
- [落库断言](db/assert-intake.sql)：以 `reqCode` 关联核验申请、客户、文件和签章记录。

## 执行

准备本机私有配置和两张已授权的测试证件图片后，在项目根目录运行：

```powershell
.\eeds\loan-apply\scripts\run-intake.ps1
```

完整流程会向测试环境写入进件数据。验证码可填任意六位数字；活体接口按测试环境挡板的真实路径调用。实际运行前请确认专用测试客户、产品码和数据清理口径。
