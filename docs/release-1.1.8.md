# ZzzHe TMA Analysis 1.1.8

EXE 的 Windows 程序清单声明 `requireAdministrator`。双击启动时，Windows 自动显示管理员授权提示；确认后以管理员身份运行，取消则不启动。已处于管理员权限的启动环境由 Windows 按现有权限处理。

构建流程会检查 EXE 内嵌清单，确认管理员权限声明存在且不申请 UIAccess，再签名和打包。延续 1.1.7 的数据处理和内存释放改进。

保留原有 ZzzHe 作者自签名与时间戳；自签名不代表 Windows 公开信任。完整解压后运行主程序并保留依赖，旧版包不覆盖。
