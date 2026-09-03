# Use the AdCraft Recommended Assets Library

The optional Recommended Assets package adds ready-to-use character and scene references to AdCraft. It works with both Docker and native deployment and does not require browser uploads.

## 1. Download the release files

Open the [AdCraft Releases page](https://github.com/GML-MMGroup/AdCraft/releases) and find the release tagged `recommended-assets-v1.0.0`. Download these two files into the same folder:

- `adcraft-recommended-assets-v1.0.0.zip`
- `adcraft-recommended-assets-v1.0.0.zip.sha256`

The release notes are optional. The ZIP is already the final archive; do not place it inside another ZIP.

## 2. Verify the download

Linux, from the download folder:

```bash
sha256sum -c adcraft-recommended-assets-v1.0.0.zip.sha256
```

Continue only when the result says `OK`.

Windows PowerShell, from the download folder:

```powershell
$zip = '.\adcraft-recommended-assets-v1.0.0.zip'
$checksum = '.\adcraft-recommended-assets-v1.0.0.zip.sha256'
$expected = ((Get-Content -Raw $checksum) -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'SHA-256 verification failed. Download both files again.' }
'SHA-256 OK'
```

## 3. Extract it into AdCraft's data directory

When AdCraft was started with any supplied one-command launcher, its host data directory is:

```text
<AdCraft project>/runtime-data/api/
```

Extract the ZIP below `assets/catalogs/recommended/` inside that directory.

Linux:

```bash
cd /path/to/AdCraft
mkdir -p runtime-data/api/assets/catalogs/recommended
unzip /path/to/downloads/adcraft-recommended-assets-v1.0.0.zip \
  -d runtime-data/api/assets/catalogs/recommended
```

Windows PowerShell:

```powershell
Set-Location C:\path\to\AdCraft
$zip = (Resolve-Path 'C:\path\to\downloads\adcraft-recommended-assets-v1.0.0.zip').Path
$target = '.\runtime-data\api\assets\catalogs\recommended'
New-Item -ItemType Directory -Force $target | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $target -Force
```

If the backend is started manually with a custom `MEDIA_DATA_DIR`, replace `runtime-data/api` above with that directory. The final location must always be:

```text
<MEDIA_DATA_DIR>/assets/catalogs/recommended/v1.0.0/
```

## 4. Check the extracted structure

The ZIP already contains the `v1.0.0` folder. The result must be exactly one version folder below `recommended`:

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

Avoid an extra archive-name folder or a second `v1.0.0` folder. Version 1.0.0 contains 41 characters, 20 scenes, and 61 previews. License and attribution information is in `LICENSES.json`.

## 5. Use the assets

Start AdCraft if it is not running, then open or refresh the **Recommended Assets** page. The backend discovers the local package and indexes its metadata in the background. Wait until the page reports that the catalog is ready.

No browser re-upload and no installation API call are required. Indexing does not copy the original media files, so keep the extracted package in place while using AdCraft.

## If the catalog does not appear

1. Confirm that `catalog.json` is directly inside `recommended/v1.0.0/`.
2. Confirm that SHA-256 verification passed and extraction finished completely.
3. Confirm that the account running AdCraft can read every extracted file.
4. Refresh the Recommended Assets page and allow indexing to finish.
5. If the page reports an invalid catalog, remove the incomplete `v1.0.0` folder, extract the verified ZIP again, and inspect the AdCraft API logs.
