# 上位机 EXE 打包与使用说明

## 1. 打包环境
- Windows 10/11
- 已安装 Python（建议在 `myenv312` 里执行）
- 能访问网络下载安装 `pip` 依赖

## 2. 一键打包（包含 QT + Web + 启动器）
在项目根目录执行：

```powershell
conda activate myenv312
cd E:\E_EngineeringWarehouse\202604_2\stm32_2\host
powershell -ExecutionPolicy Bypass -File .\build_full_exe_release.ps1
```

可选参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_full_exe_release.ps1 `
  -QtName AliyunQtHost `
  -WebName WebDashboard `
  -LauncherName StartAll `
  -ReleaseDir .\dist\release
```

如果不希望把当前密钥配置打进发布包：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_full_exe_release.ps1 -NoCopyDotEnv
```

## 3. 打包产物
默认输出目录：`host\dist\release`

会包含：
- `AliyunQtHost.exe`（QT 上位机）
- `WebDashboard.exe`（Web 看板服务）
- `StartAll.exe`（同时启动两者）
- `start_all.bat`
- `start_qt.bat`
- `start_web.bat`
- `.env.example`
- `.env`（默认会复制你打包机当前配置；可用 `-NoCopyDotEnv` 关闭）
- `README_使用说明.md`
- `.dashboard_access`

## 4. 运行方式
推荐：
1. 双击 `start_all.bat`
2. 浏览器打开 `http://127.0.0.1:8000/`
3. 局域网设备可访问 `http://你的电脑IP:8000/`

也可以分别启动：
- 只开上位机：`start_qt.bat`
- 只开看板：`start_web.bat`

## 5. 配置文件说明
- `WebDashboard.exe` 同目录可放 `.env`，用于阿里云与 Web 参数配置。
- 默认会把打包机当前 `.env` 复制到发布目录。
- 也可手动用 `.env.example` 覆盖成新 `.env` 再修改。
- `.dashboard_access`：
  - `1` 允许访问看板
  - `0` 禁止访问看板（页面返回 503）
  - QT 里“开启/关闭访问”会自动改这个文件

## 6. 常见问题
- 启动后网页打不开：
  - 检查 `WebDashboard.exe` 是否已运行
  - 检查 `.dashboard_access` 是否为 `1`
  - 检查防火墙是否拦截 8000 端口
- 手机无法访问：
  - 确认手机和电脑在同一局域网
  - 使用 QT 页面显示的局域网地址或二维码
- 杀毒软件误报：
  - 部分打包 exe 可能触发误报，需加入信任
