# Fear Nightfall: Remains of Chaos

Подготовка сборки 1.2.0 для LANMinecraft. [Авторский клиентский выпуск](https://www.curseforge.com/minecraft/modpacks/fear-nightfall/files/9389072)

`tools/upstream-client-lock.json` фиксирует SHA256 и размер оригинального ZIP, ссылки на официальный источник, записи зависимостей и SHA256 файлов внутри авторских overrides. Minecraft и загрузчик взяты из оригинального манифеста. Java в `portable-pack.json` соответствует выбору текущего лаунчера для этой версии Minecraft и проверяется при запуске.

## Восстановление авторского клиента

Закреплённый авторский клиент CurseForge использует project ID 887839 и file ID 9389072.
Для подготовки текущего кандидата из корня LANMinecraft запустите:

```powershell
python -B tools/PackData/CurseForge/release_overlay.py stage --pack-source LocalSources/Fear-Nightfall-Remains-of-Chaos --output $stage
```

`tools/overlay.json` сохраняет политику открытия мира через Steam. Для нового авторского выпуска снимите отдельную квитанцию через `prepare.py --client-only` и проверьте её командой `release_overlay.py review-update`. При изменении защищённого входа пересмотрите рецепт и закрепите новые точные байты. После нативной проверки сохраните полный `tools/upstream-lock.json` и выполните `release_overlay.py verify` по готовому манифесту.

Авторский Luna 5.3.1 (`880620/6599106`, SHA256 `26635aa32433775d9f10403d928a2008cb38173032c25720c52d33fd2cb4b1c8`) остаётся в lock и исключается из игровой поставки. Его `ServerConnectionListenerMixin` при открытии мира запускает отдельное реле через `QuiclimeSession.startAsync()`. Настройки Luna задают выбор реле и его адрес. В JAR есть только реализация сетевой публикации и её зависимости. В метаданных остальных модов ссылок на Luna нет. Открытие мира и закрытие публикации выполняет e4steam. [Авторский Luna 5.3.1](https://www.curseforge.com/minecraft/mc-mods/luna/files/6599106)

No Report Button 1.5.0 (`658722/4594978`, SHA256 `9f6a4af984632c7a7a673907303c5d69bd3016634ed48b328aa30a24cd0c0416`) остаётся в lock и исключается из игровой поставки. Его `GameMenuScreenMixin` после открытия мира переименовывает «Жалобы» в «Открыть для сети» и выключает кнопку. Проверенный JAR не предусматривает настройки для этого действия. Обе кнопки используют одну позицию в оформлении FancyMenu. No Chat Reports и его настройки поставляются из авторских файлов. [No Report Button 1.5.0](https://www.curseforge.com/minecraft/mc-mods/no-report-button/files/4594978)

`tools/curseforge-placements.json` закрепляет 28 архивов. Ресурсы и шейдеры
размещаются по официальным классам проектов. Два datapack версии 1.2
совпали по SHA256 с файлами в корневой папке `datapacks` серверного
выпуска 1.2.0. Авторские версии 1.0 в обеих папках Paxi сохраняются.
Для Quark Bark Cutting Compat официальный файл совпал по SHA256 с
обеими авторскими копиями, а запись зависимости указывает на
`config/paxi/datapacks`. [Официальный серверный выпуск](https://www.curseforge.com/minecraft/modpacks/fear-nightfall/files/9389089)

`tools/curseforge-fallbacks.json` закрепляет Noisium Forge `930207/5650506`
для случая `{"data":null}` у CurseForge. Оригинальный CDN JAR совпал
с членом `mods/noisium-forge-2.3.0+mc1.20-1.20.1.jar` того же серверного
архива. Размер 218 152 байта, CRC32 `21f88094`, SHA256
`b0b020250c81e8cce7776c3dc8f7085f269e2007570d5fbd492c4497ad60685c`.

## Публикация

Условия авторского источника — All Rights Reserved.

Пользователь подтвердил наличие разрешения на перезалив. Публикация следует после проверки полного состава и нативной приёмки.
