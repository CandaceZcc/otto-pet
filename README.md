# 电棍otto Codex Pet

基于当前目录里的 Otto GIF 素材制作的 Codex 自定义 pet。成品保留真人直播切片的 meme 感，按 Codex pet contract 打包为 `pet.json` + `spritesheet.webp`。

## 预览

构建后可查看 QA 图：

```powershell
Start-Process .\pet-build\qa\contact-sheet.png
```

各状态动图预览位于：

```text
pet-build/qa/previews/
```

## 本地安装

在 PowerShell 中从仓库根目录执行：

```powershell
$dest = Join-Path $env:USERPROFILE ".codex\pets\diangun-otto"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item .\pet\diangun-otto\pet.json $dest -Force
Copy-Item .\pet\diangun-otto\spritesheet.webp $dest -Force
```

重启 Codex 后，在自定义 pet 列表中选择 `电棍otto`。

## 重新构建

依赖：

```powershell
python -m pip install pillow
```

生成 pet、QA 预览和可发布包：

```powershell
python .\tools\build_otto_pet.py
```

输出位置：

```text
pet/diangun-otto/pet.json
pet/diangun-otto/spritesheet.webp
pet-build/qa/contact-sheet.png
pet-build/qa/previews/
```

## 校验

如果本机安装了 hatch-pet skill，可运行：

```powershell
python "$env:USERPROFILE\.codex\skills\hatch-pet\scripts\validate_atlas.py" .\pet\diangun-otto\spritesheet.webp --json-out .\pet-build\final\validation.json
python "$env:USERPROFILE\.codex\skills\hatch-pet\scripts\inspect_frames.py" --frames-root .\pet-build\frames --json-out .\pet-build\qa\frames-review.json
```

## codex-pets.net 上传

1. 打开 https://codex-pets.net/#/upload
2. 上传 `pet/diangun-otto/pet.json` 和 `pet/diangun-otto/spritesheet.webp`
3. 上传完成后，把网站生成的链接或命令发回来。
4. TODO: 在这里补充上传后生成的一键安装命令。

## 文件说明

- `tools/build_otto_pet.py`：从原始 GIF 清洗、补色、抽帧并生成 Codex pet。
- `pet/diangun-otto/`：可直接安装或上传的最终 pet package。
- `pet-build/`：构建产物和 QA 文件，可重新生成。
- `*.gif`：原始素材。
