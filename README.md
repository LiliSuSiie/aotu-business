# Aotu Business 项目说明

本项目保存不同产品的业务自动化方案、执行脚本和测试记录。

## 从 GitHub 下载后首次准备

仓库包含代码、配置模板及说明；真实账号配置、原始业务录制、运行台账和报告保留在本机，不上传。

将项目下载或克隆到本机后，在项目目录打开 PowerShell，执行：

```powershell
python -m pip install -r .\taian\requirements.txt
if (-not (Test-Path .\taian\config\review.private.json)) {
    Copy-Item .\taian\config\review.example.json .\taian\config\review.private.json
}
notepad .\taian\config\review.private.json
```

仅在私有配置尚不存在时复制模板；如果已有配置，直接打开修改，避免覆盖自己的账号。填写实际服务地址、明文用户名和密码并保存后，执行：

```powershell
python .\taian\scripts\run_review.py --no-report
```

下面的新手指南按原电脑安装位置举例；下载到其他位置时可使用上面这些相对于项目目录的命令。

## 我想自己运行泰安评议

请打开 **[泰安评议：新手运行指南](taian/README.md)**，从“第一步”开始操作。指南包括账号配置、打开终端、选择批次和评议员、不生成报告的运行方式，以及常见问题处理。

已经配置好账号后，在 Windows PowerShell 中复制下面这一行，按回车：

```powershell
python "E:\liwenqiu\project\aotu-business\taian\scripts\run_review.py" --no-report
```

程序会让你先选择评议批次，再选择评议员。**第二次选择后会开始实际保存，该次运行只处理选中的一名评议员。** 当前评议内容使用此前确认的测试规则：是否了解、是否适宜授信和全部评议要素都为 true。

## 产品目录

| 目录 | 内容 |
| --- | --- |
| [taian](taian/README.md) | 泰安评议自动化、新手指南和账号配置说明 |
| [鄂尔多斯进件](eeds/loan-apply/README.md) | 独立的进件接口自动化资产 |
| [鄂尔多斯续授信](eeds/renew-credit-automation/README.md) | 独立的续授信自动化资产 |
| [接口录制器](network-recorder-extension/README.md) | 浏览器接口录制与 JSON 导出工具 |

各产品的配置和脚本分别维护；泰安评议的生成文件统一放在 taian 目录下。
