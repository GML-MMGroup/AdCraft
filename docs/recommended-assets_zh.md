# 使用 AdCraft 推荐资产库

可选的 Recommended Assets 资源包可以为 AdCraft 添加可直接使用的角色和场景参考素材。Docker 部署和非 Docker 部署都能使用，而且不需要通过浏览器重新上传图片。

## 1. 下载 Release 文件

打开 [AdCraft Releases 页面](https://github.com/GML-MMGroup/AdCraft/releases)，找到标签为 `recommended-assets-v1.0.0` 的 Release，将以下两个文件下载到同一个文件夹：

- `adcraft-recommended-assets-v1.0.0.zip`
- `adcraft-recommended-assets-v1.0.0.zip.sha256`

Release notes 可以不下载。ZIP 已经是最终压缩包，不要再次把它放进另一个 ZIP。

## 2. 校验下载文件

Linux，在下载目录中运行：

```bash
sha256sum -c adcraft-recommended-assets-v1.0.0.zip.sha256
```

只有结果显示 `OK` 才继续。

Windows PowerShell，在下载目录中运行：

```powershell
$zip = '.\adcraft-recommended-assets-v1.0.0.zip'
$checksum = '.\adcraft-recommended-assets-v1.0.0.zip.sha256'
$expected = ((Get-Content -Raw $checksum) -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'SHA-256 校验失败，请重新下载两个文件。' }
'SHA-256 校验通过'
```

## 3. 解压到 AdCraft 数据目录

通过项目自带的任意一键启动器运行 AdCraft 时，宿主机上的数据目录都是：

```text
<AdCraft 项目>/runtime-data/api/
```

将 ZIP 解压到该目录中的 `assets/catalogs/recommended/` 下。

Linux：

```bash
cd /path/to/AdCraft
mkdir -p runtime-data/api/assets/catalogs/recommended
unzip /path/to/downloads/adcraft-recommended-assets-v1.0.0.zip \
  -d runtime-data/api/assets/catalogs/recommended
```

Windows PowerShell：

```powershell
Set-Location C:\path\to\AdCraft
$zip = (Resolve-Path 'C:\path\to\downloads\adcraft-recommended-assets-v1.0.0.zip').Path
$target = '.\runtime-data\api\assets\catalogs\recommended'
New-Item -ItemType Directory -Force $target | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $target -Force
```

如果手动启动后端，并自定义了 `MEDIA_DATA_DIR`，请用该目录替换上面的 `runtime-data/api`。最终位置必须是：

```text
<MEDIA_DATA_DIR>/assets/catalogs/recommended/v1.0.0/
```

## 4. 检查解压结构

ZIP 内已经包含 `v1.0.0` 文件夹。`recommended` 下只能有一层版本目录，正确结构如下：

```text
runtime-data/api/assets/catalogs/recommended/
└── v1.0.0/
    ├── catalog.json
    ├── LICENSES.json
    ├── originals/
    │   ├── characters/
    │   └── scenes/
    └── previews/
        ├── characters/
        └── scenes/
```

不要多套一层压缩包名称目录，也不要出现两层 `v1.0.0`。1.0.0 版本包含 41 个角色、20 个场景和 61 张预览图。授权和署名信息位于 `LICENSES.json`。

## 5. 使用资产

如果 AdCraft 尚未运行，先启动项目，然后打开或刷新 **Recommended Assets** 页面。后端会发现本地资源包，并在后台索引元数据；等待页面显示资产库已经就绪。

不需要通过浏览器重新上传，也不需要调用安装接口。索引过程不会复制原始媒体文件，因此使用 AdCraft 期间要保留解压后的资源包。

## 资产库没有显示时

1. 确认 `catalog.json` 直接位于 `recommended/v1.0.0/` 中。
2. 确认 SHA-256 校验通过，而且解压已经完整结束。
3. 确认运行 AdCraft 的账户能够读取所有解压文件。
4. 刷新 Recommended Assets 页面，并等待索引完成。
5. 如果页面提示资产库无效，删除未完整解压的 `v1.0.0` 文件夹，重新解压已经通过校验的 ZIP，并查看 AdCraft API 日志。
