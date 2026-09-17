[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\intake-run.local.json'),
    [ValidateSet('read', 'prepare', 'full')]
    [string]$Mode = 'full',
    [switch]$SkipDb
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$k6Script = Join-Path $projectRoot 'k6\intake-application-flow.js'
$dbScript = Join-Path $projectRoot 'db\assert-intake.sql'

function Require-Value([object]$Value, [string]$Name) {
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value) -or [string]$Value -like 'replace-with-*') {
        throw "缺少私有配置项：$Name"
    }
}

function Escape-SqlLiteral([string]$Value) {
    return $Value.Replace('\\', '\\\\').Replace("'", "''")
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "未找到私有运行配置：$ConfigPath。请复制 config/intake-run.example.json 为 intake-run.local.json 后填写。"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
Require-Value $config.baseUrl 'baseUrl'
Require-Value $config.authorization 'authorization'
Require-Value $config.enterpriseCode 'enterpriseCode'
if ($Mode -ne 'read') { Require-Value $config.productCode 'productCode' }

if ($Mode -eq 'full') {
    foreach ($item in @(
        @{ Value = $config.customer.name; Name = 'customer.name' },
        @{ Value = $config.customer.idCardNo; Name = 'customer.idCardNo' },
        @{ Value = $config.customer.phoneNumber; Name = 'customer.phoneNumber' },
        @{ Value = $config.customer.cipher.name; Name = 'customer.cipher.name' },
        @{ Value = $config.customer.cipher.idCardNo; Name = 'customer.cipher.idCardNo' },
        @{ Value = $config.customer.cipher.phoneNumber; Name = 'customer.cipher.phoneNumber' },
        @{ Value = $config.customer.cipher.contactName; Name = 'customer.cipher.contactName' },
        @{ Value = $config.customer.cipher.contactPhone; Name = 'customer.cipher.contactPhone' },
        @{ Value = $config.application.verifyCode; Name = 'application.verifyCode' }
    )) { Require-Value $item.Value $item.Name }

    if ($config.application.verifyCode -notmatch '^\d{6}$') {
        throw 'application.verifyCode 必须是 6 位数字；测试环境挡板会将任意 6 位数字判定为通过。'
    }
    foreach ($image in @('id-front.jpg', 'id-back.jpg')) {
        $path = Join-Path $projectRoot "k6\fixtures\$image"
        if (-not (Test-Path -LiteralPath $path)) { throw "缺少本地测试图片：$path" }
    }
}

$k6 = (Get-Command k6 -ErrorAction SilentlyContinue).Source
if (-not $k6) {
    $installedK6 = 'C:\Program Files\k6\k6.exe'
    if (Test-Path -LiteralPath $installedK6) { $k6 = $installedK6 }
}
if (-not $k6) { throw '未找到 k6.exe；请确认 k6 已安装或加入 PATH。' }

$variables = [ordered]@{
    BASE_URL = $config.baseUrl
    AUTHORIZATION = $config.authorization
    ENTERPRISE_CODE = $config.enterpriseCode
    PRODUCT_CODE = $config.productCode
    MODE = $Mode
    DISPLAY_NAME = $config.customer.displayName
    NAME_CIPHER = $config.customer.cipher.name
    ID_CARD_CIPHER = $config.customer.cipher.idCardNo
    PHONE_CIPHER = $config.customer.cipher.phoneNumber
    CONTACT_NAME_CIPHER = $config.customer.cipher.contactName
    CONTACT_PHONE_CIPHER = $config.customer.cipher.contactPhone
    VERIFY_CODE = $config.application.verifyCode
    ID_IMG_BASE64 = $config.customer.idImgBase64
    APPLY_AMOUNT = $config.application.applyAmount
    LOAN_USE = $config.application.loanUse
    LOAN_USE_DESC = $config.application.loanUseDesc
}

$arguments = @('run', '--quiet')
foreach ($pair in $variables.GetEnumerator()) {
    if ($null -ne $pair.Value -and -not [string]::IsNullOrWhiteSpace([string]$pair.Value)) {
        $arguments += '-e'
        $arguments += ('{0}={1}' -f $pair.Key, $pair.Value)
    }
}
$arguments += $k6Script

Write-Host "开始执行进件流程（模式：$Mode）。敏感配置不会输出。"
$output = @(& $k6 @arguments 2>&1 | ForEach-Object { $_.ToString() })
$output | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { throw "k6 执行失败，退出码：$LASTEXITCODE" }

if ($Mode -ne 'full') { exit 0 }
$resultLine = $output | Where-Object { $_ -match 'ATRC_INTAKE_RESULT\s+\{' } | Select-Object -Last 1
if (-not $resultLine -or $resultLine -notmatch '"reqCode"\s*:\s*"([^"]+)"') {
    throw '脚本未输出 reqCode，无法执行落库核验。'
}
$reqCode = $Matches[1]
Write-Host "进件接口执行完成，reqCode：$reqCode"

if ($SkipDb -or -not $config.db.enabled) {
    Write-Host '已跳过数据库核验（db.enabled=false 或指定 -SkipDb）。'
    exit 0
}
Require-Value $config.db.database 'db.database'
Require-Value $config.db.defaultsExtraFile 'db.defaultsExtraFile'
if (-not (Test-Path -LiteralPath $config.db.defaultsExtraFile)) { throw 'db.defaultsExtraFile 指向的 MySQL 私有连接配置不存在。' }
$mysql = $config.db.mysqlPath
if (-not $mysql) { $mysql = (Get-Command mysql -ErrorAction SilentlyContinue).Source }
if (-not $mysql -or -not (Test-Path -LiteralPath $mysql)) { throw '未找到 MySQL 客户端；请填写 db.mysqlPath。' }

$sql = Get-Content -LiteralPath $dbScript -Raw -Encoding UTF8
$sql = $sql.Replace('{{REQ_CODE}}', (Escape-SqlLiteral $reqCode))
$sql = $sql.Replace('{{CUSTOMER_NAME}}', (Escape-SqlLiteral $config.customer.name))
$sql = $sql.Replace('{{ID_CARD_NO}}', (Escape-SqlLiteral $config.customer.idCardNo))
$sql = $sql.Replace('{{PHONE_NUMBER}}', (Escape-SqlLiteral $config.customer.phoneNumber))
Write-Host '开始数据库落库核验（结果不回显身份信息）。'
$sql | & $mysql "--defaults-extra-file=$($config.db.defaultsExtraFile)" '--batch' '--skip-column-names' $config.db.database
if ($LASTEXITCODE -ne 0) { throw "数据库核验失败，退出码：$LASTEXITCODE" }
