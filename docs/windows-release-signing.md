# Windows 发布签名配置

自 0.35.2 起提供本地测试签名，当前新版为 0.36.4，使用独立的自签名证书；本机尚无公开受信任的正式代码签名证书。构建流程不改变 Windows 的 SmartScreen、Defender 或证书信任设置，旧版 EXE 保持不变。

## 本地签名测试版

本地配置：`%LOCALAPPDATA%\ZzzHeTMA\local-signing.json`，与下面的正式证书配置独立。证书主题为 `CN=ZzzHe Local Test`，RSA 3072 位，代码签名用途，有效期三年。私钥为不可导出，只保存在 `Cert:\CurrentUser\My` 中；程序包里的 `ZzzHe-Local-Test.cer` 仅含公钥。请不要将该证书当作公开可信发行者证明。

```powershell
# 第一次创建本地证书；已有配置会复用，不反复生成证书
powershell -NoProfile -ExecutionPolicy Bypass -File tools\sign_windows_local.ps1 -InitializeCertificate

# 打包并附加本地签名及 RFC3161 时间戳
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows.ps1 -DistPath dist-0.37.5 -LocalTestSigning

# 只检查已有包，不重新签名
powershell -NoProfile -ExecutionPolicy Bypass -File tools\sign_windows_local.ps1 -PackagePath "dist-0.37.5\ZzzHe TMA Analysis" -CheckOnly
```

脚本只写当前用户的个人证书库，不向 Root 或 TrustedPublisher 添加证书。签名后检查嵌入的签名者指纹、时间戳及 Windows Authenticode 文件校验结果。本地流程单独记录 `local_test_signed_timestamped`；预期 Windows 返回 `CERT_E_UNTRUSTEDROOT`（0x800B0109），这表示证书不受信任，不是 Windows 信任校验通过。PowerShell 的签名状态可能显示 `UnknownError`，实际原因可在 `release-security.json` 的 `winverifytrust_code` 中查看。文件摘要损坏、签名者错误或无时间戳均拒绝发布。

本地签名不满足正式流程的 `-RequireSignature`；两种构建参数不能混用，也不会通过安装根证书来更改 Windows 的信任结论。数字签名覆盖主 EXE，不覆盖整个依赖目录。

## 已准备的配置

配置位置：`%LOCALAPPDATA%\ZzzHeTMA\release-signing.json`（本机为 `C:\Users\Administrator\AppData\Local\ZzzHeTMA\release-signing.json`）。与应用配置放在同一目录，已有配置不会被初始化命令覆盖。

```json
{
  "version": 1,
  "enabled": false,
  "store_location": "CurrentUser",
  "certificate_thumbprint": "",
  "timestamp_url": "http://timestamp.digicert.com",
  "signtool_path": ""
}
```

`signtool_path` 留空会自动查找 Windows SDK 中的工具；也可填写完整路径。本机已找到 SDK 10.0.26100.0 的 x64 工具。时间戳使用 RFC3161；文件摘要和时间戳摘要均为 SHA256。`/sha1` 参数只是查找证书指纹，不代表文件采用 SHA1 签名。

## 以后取得证书时

1. 将正规代码签名证书按照证书机构的说明配置到 Windows 的个人证书库（My），并保证签名进程可以使用其私钥或硬件设备。当前脚本支持证书库方式；云签名服务需要另外接入其官方客户端。
2. 在配置中填写公开的 40 位 `certificate_thumbprint`，选择 `CurrentUser` 或 `LocalMachine`，再将 `enabled` 设为 `true`。不要在配置中放密码、PFX、私钥或访问令牌。
3. 在项目目录先执行检查，再进行正式构建：

```powershell
# 初始化配置；已有文件保持不变
powershell -NoProfile -ExecutionPolicy Bypass -File tools\sign_windows_release.ps1 -InitializeConfig

# 只检查配置、证书链及当前程序签名，不写入或签名程序
powershell -NoProfile -ExecutionPolicy Bypass -File tools\sign_windows_release.ps1 -PackagePath "dist-0.35.1\ZzzHe TMA Analysis" -CheckOnly -RequireSignature

# 强制签名的正式构建；缺少证书时在打包前失败
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_windows.ps1 -DistPath dist-release -RequireSignature
```

命令中的 `-ExecutionPolicy Bypass` 只允许本次 PowerShell 进程执行项目自带的构建脚本，不修改系统的持久执行策略，也不能替代 EXE 签名或消除 SmartScreen 提示。不要对不可信脚本使用该参数。

已有包也可执行签名，无需重建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\sign_windows_release.ps1 -PackagePath "dist-release\ZzzHe TMA Analysis" -RequireSignature
```

签名前会检查证书有效期、私钥、代码签名用途和本机证书链，并拒绝自签名叶证书。脚本签名的是同目录临时副本；仅在 SignTool 签名、时间戳、Authenticode 校验以及签名者指纹均通过后替换原 EXE。失败时清理本次临时文件并保留原程序。证书机构或硬件可能仍要求用户交互或 PIN，脚本不会储存它们。

签名完成后生成 `release-security.json` 和 `SHA256SUMS.txt`。校验和文件目前只覆盖主 EXE，不是整个目录的安全认证。任何后续修改 EXE 的动作都必须在签名前完成。分发时保留整个应用目录，签名不替代依赖文件。

## 目前的测试版

正式配置中的 `enabled: false` 允许构建未签名测试包，并明确记录 `NotSigned`，不会伪装发行者。`-RequireSignature` 会拒绝这种配置。0.35.2 的本地测试签名通过独立配置显式启用；0.35.1 主程序未修改。

代码签名用于验证发行者和文件完整性；新签名文件仍可能因为信誉不足出现 SmartScreen 提示。自签名证书不能为其他电脑建立公开信任，修改程序显示的公司名称也不等于获得可信签名。此处没有承诺取得证书后立即免提示。

参考：[微软 SmartScreen 信誉说明](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)、[SignTool 官方参数](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)、[Azure Artifact Signing 集成](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations)。
