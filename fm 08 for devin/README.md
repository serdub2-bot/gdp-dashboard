# Football Manager 2008 `fm.exe` — статический разбор для передачи

**Цель:** дать следующему аналитику проверяемую исходную точку по PE-файлу, перечень воспроизводимых инвентарей и адресные ориентиры. Это статический разбор одного конкретного файла, не утверждение о поведении программы во время игры.

**Исходный файл не изменялся.** Разбор выполнен над отдельной копией, извлечённой в `/tmp/fm_analysis/fm.exe`. Игровые сохранения не открывались и не менялись. Папка содержит отчёт, скрипт и текстовые инвентари; копии `fm.exe` здесь нет.

## Отдельно: анализ присланных файлов базы данных

В этой же handoff-папке добавлен самостоятельный read-only разбор исходных `*.dat` и `802.xml`: [`inventory/database/README.md`](inventory/database/README.md). Он охватывает контейнеры `client_db.dat`, `server_db.dat`, `lang_db.dat`, обе группы history-файлов, контрольные хэши, карту языковых zlib-потоков и структурные связи history-index → offset pairs → data. Это отдельная тема и не повторяет анализ игровых/лиговых экспериментов. Скрипт воспроизведения: [`database_analysis.py`](database_analysis.py); все результаты находятся в [`inventory/database/`](inventory/database/).

## 1. Идентификация и воспроизводимость

| Поле | Значение |
|---|---|
| Входной архив | `inbox/fm.zip` — один файл `fm.exe` |
| SHA-256 архива | `ea6bda5884387a606aa5c92a43f91723dacfafb0973fb33cbcea26585a1c444f` |
| Размер EXE | 22,249,472 байта (21.2 MiB) |
| SHA-256 EXE | `9725365b4996622c122e37f9f91c903c2ccef112f32121d33db000ed9012d42b` |
| MD5 EXE | `3356708b1c3e67769df405de94c34f3f` |
| Версия из Version Resource | `8.0.2`; `ProductVersion 8.0.2f117931` |
| Product/Company | Football Manager 2008 / Sports Interactive |
| GDF XML | указывает дату релиза `2007-10-19` |
| PE timestamp | `2008-02-14 04:29:58 UTC` — значение заголовка PE, не доказательство даты сборки/поставки |

### Повторить извлечение и инвентаризацию

Из корня репозитория, в POSIX shell. Команды создают отдельную копию во временной папке и не меняют ни архив, ни исходную игру:

```sh
mkdir -p /tmp/fm_analysis
unzip -p inbox/fm.zip fm.exe > /tmp/fm_analysis/fm.exe
sha256sum /tmp/fm_analysis/fm.exe
python3 -m pip install --target /tmp/fm_analysis/pydeps pefile capstone
PYTHONPATH=/tmp/fm_analysis/pydeps \
  python3 'fm 08 for devin/analyze_fm2008_exe.py' \
  /tmp/fm_analysis/fm.exe --out /tmp/fm_analysis/inventory
PYTHONPATH=/tmp/fm_analysis/pydeps \
  python3 'fm 08 for devin/deep_analysis.py' \
  /tmp/fm_analysis/fm.exe --out /tmp/fm_analysis/deep
PYTHONPATH=/tmp/fm_analysis/pydeps \
  python3 'fm 08 for devin/authenticode_check.py' /tmp/fm_analysis/fm.exe
```

Для повторения уже приложенных inventories замените каталог после `--out` на `'fm 08 for devin/inventory'` (скрипт перезапишет только файлы инвентаря). Дополнительные точечные проверки:

```sh
unzip -l inbox/fm.zip
objdump -f -h -p /tmp/fm_analysis/fm.exe
strings -a -t x -n 4 /tmp/fm_analysis/fm.exe > /tmp/fm_analysis/strings.txt
```

`analyze_fm2008_exe.py` требует `pefile`, читает входной файл и записывает JSON/CSV/TXT/GZIP в `--out`; бинарник не патчит. Скрипт также формирует грубый поиск `E9 rel32` переходов из `.text` в `.cave`; это поиск байтовых кандидатов, а не универсальный дизассемблер. При необходимости отдельную дизассемблировку можно повторить с `objdump` либо поставить `capstone` во временный каталог, не в репозиторий.

## 2. PE-идентификация и структура

PE32 для x86/i386, Windows GUI. ImageBase `0x00400000`, entry RVA `0x00d30153`, entry VA `0x01130153`, SizeOfImage `0x01805000`, SizeOfHeaders `0x1000`. Entry RVA попадает в `.text`; файловое смещение entry point — `0x00d30153`.

| Секция | RVA | VA при ImageBase `0x400000` | Virtual size | File offset | Raw size | Характеристики |
|---|---:|---:|---:|---:|---:|---|
| `.text` | `0x1000` | `0x401000` | `0xe18db2` | `0x1000` | `0xe19000` | code, execute/read |
| `.rdata` | `0xe1a000` | `0x125a000` | `0x662f77` | `0xe1a000` | `0x663000` | initialized data, read |
| `.data` | `0x147d000` | `0x187d000` | `0x362238` | `0x147d000` | `0x94000` | initialized data, read/write |
| `.rsrc` | `0x17e0000` | `0x1be0000` | `0x23fe8` | `0x1511000` | `0x24000` | resources, read |
| `.cave` | `0x1804000` | `0x1c04000` | `0x1000` | `0x1537000` | `0x1000` | code, execute/read |

Особенности:

- COFF timestamp `2008-02-14 04:29:58 UTC`; linker version `7.10`; COFF characteristics `0x010f` (executable, 32-bit, relocations stripped); Windows GUI subsystem. `DllCharacteristics=0` и relocation directory отсутствует, поэтому стандартные PE ASLR/NX capability bits не выставлены. Это характеристики заголовка, не оценка runtime hardening.
- Entry-point bytes по `0x01130153` отдельно сохранены в [`inventory/deep/entrypoint_disassembly.txt`](inventory/deep/entrypoint_disassembly.txt). Начало использует локальные helper calls и IAT indirect calls, затем обновляет глобальные поля/проверяет MZ signature у указателя; без CFG/символов это описывает только видимые инструкции, не называет startup-функцию.
- `.data` имеет virtual size `0x362238`, но на диске занимает `0x94000`; остаток виртуального диапазона не является raw-данными файла.
- Имена/порядок секций не являются доказательством их происхождения. В частности, `.cave` — наблюдаемое имя и исполнение секции, а не атрибуция автора патча.
- Data directories: Export RVA `0x1479d00`, Import RVA `0x1478444`, Resource RVA `0x17e0000`, Security Directory **file offset** `0x1535000`, размер `0x1500`, Debug RVA `0xe1a4b0`, Load Config RVA `0x12bf020`, IAT RVA `0xe1a000`. Relocation, TLS, Delay Import и CLR/COM descriptors отсутствуют.
- Debug Directory содержит одну запись CodeView `RSDS`: PDB GUID `3C1DEAC9-10D8-4E84-BEC1-8ACEBBCCE806`, age `1`; встроенный путь `E:\perforce_data\code\releases\fm\8.0.2\english\game\builds\win32\release final\application\fm.pdb`. Сам `.pdb` в workspace не найден. GUID+age — точный ключ для поиска matching PDB у владельца символов.
- В security directory лежит PKCS#7/Authenticode-контейнер. В сертификатном наборе есть сертификат подписанта `Sega Europe Limited` и цепочка/временная метка VeriSign/Thawte.
- Дополнительная проверка PE image digest выявила **несовпадение**: SHA-1, записанный в `SpcIndirectDataContent`, `6cbea0a5633e6139dd2f70a1fe241dd4b379e279`; рассчитанный Authenticode SHA-1 текущего файла — `af461bf88674c836f07cb04c75fed7885d31453d`. Значит, встроенная подпись **не подтверждает текущие байты этого файла**. Это не устанавливает, кем и когда были изменены байты; проверка доверия цепочки сертификатов и отдельная криптографическая проверка подписи самого PKCS#7 не проводились.

Подробные, машинно-сгенерированные значения: [`inventory/summary.json`](inventory/summary.json), [`inventory/sections.csv`](inventory/sections.csv), [`inventory/directories.csv`](inventory/directories.csv).

## 3. Импорты, экспорты, ресурсы

### Импорты

283 импортируемых функции из 15 DLL. Главные группы по числу импортов: `KERNEL32.dll` (129), `USER32.dll` (49), `OPENGL32.dll` (39), `GDI32.dll` (18), `WS2_32.dll` (17), `dbghelp.dll` (10). Остальные: `IMM32.dll`, `ADVAPI32.dll`, `SHELL32.dll`, `ole32.dll`, `OLEAUT32.dll`, `WTSAPI32.dll`, `faultrep.DLL`, `DSOUND.dll`, `comdlg32.dll`.

Это указывает на Windows GUI, OpenGL-рендеринг, Winsock и отладочную/дамп-инфраструктуру. Наличие импорта не доказывает, что каждая функция вызывается в обычном игровом сценарии. Полный список по имени/DLL/IAT: [`inventory/imports.csv`](inventory/imports.csv).

### Экспорты

382 именованных экспорта. Большая часть — регионально/страново префиксированные процедуры вида `*_get_settings`, `*_setup_comps`, `*_setup_fixture_rules`, `*_setup_transfer_rules`, `*_setup_discipline_rules`; есть и специальные варианты вроде `*_setup_continental_cup_seeding`. Это убедительно выглядит как API конфигурации лиг/соревнований для региональных наборов данных, но конкретную семантику каждой функции следует проверять по телу кода и caller-ам. Полный список: [`inventory/exports.csv`](inventory/exports.csv).

### Ресурсы

PE resource tree содержит 43 data entries: именованные `DATA/__GDF_THUMBNAIL` и `DATA/__GDF_XML`, а также ID-типы `1`, `3`, `12`, `14`, `16`, `24` (стандартные категории Win32-ресурсов, включая version/manifest). GDF XML имеет размер 4,014 байт; thumbnail — 77,431 байт. Каталог с RVA, file offset, размером и codepage: [`inventory/resources.csv`](inventory/resources.csv).

Version resource и GDF XML прочитаны статически. В расширенном пакете все 43 resource payload извлечены в `inventory/deep/resource_payloads/` с исходным хэшем/размером в CSV; GDF thumbnail распознан как PNG, GDF XML сохранён в raw UTF-16LE. Остальные Windows resources оставлены бинарными иконками/bitmap/manifest payloads; полный разбор их содержимого и визуальная проверка не выполнялись.

## 4. Строки и RTTI: как читать инвентари

- Прежний GNU `strings -a -n 4` дал 187,826 строковых записей (результат зависит от реализации `strings` и классификации печатных символов).
- Скрипт приложенного анализа использует собственный ASCII-шаблон `[0x20–0x7e]{4,}` и получает 186,211 записей. Они сохранены с **file offset** в [`inventory/strings_ascii.tsv.gz`](inventory/strings_ascii.tsv.gz); распакованный формат — `file_offset<TAB>text`.
- Для MSVC RTTI использован эвристический шаблон `.?AV...@@`: 8,154 совпадения, 7,795 уникальных строк. Первая величина включает повторения, вторая — дедуплицированные имена. Список: [`inventory/rtti_type_names.txt`](inventory/rtti_type_names.txt). Это инвентарь строк, похожих на имена классов, не готовый class hierarchy: шаблоны могут пропускать типы/структуры и включать недействительные кандидаты.
- Практический поиск: `zgrep -Ei 'SCOUT_SEARCH|PERSON_SEARCH|MATCH' 'fm 08 for devin/inventory/strings_ascii.tsv.gz'`.

### Значимые строки и ориентиры поиска игроков

| Текст | File offset | VA (если в `.rdata`, ImageBase `0x400000`) | Примечание |
|---|---:|---:|---|
| `SIM_STATS` | `0x00e5b1e0` | `0x0125b1e0` | строка/идентификатор, встречается в бинарнике; одного имени недостаточно для вывода о caller-ах |
| `PERSON_SEARCH_PANEL` | `0x00e5faa4` | `0x0125faa4` | совпадает с ранее зафиксированным смещением |
| `SCOUT_SEARCH_PERSON_FILTER` | `0x00e5fee4` | `0x0125fee4` | совпадает с ранее зафиксированным смещением |
| `PLAYER_SEARCH_FILTER_ADVISOR` | `0x00e60380` | `0x01260380` | совпадает с ранее зафиксированным смещением |
| `Well-known players in your region (<%number#1> found)` | `0x01126efc` | `0x01526efc` | UI-текст поиска игроков |
| `Assign scout: Attempting to assign scout to a non-scout search` | `0x0117aedc` | `0x0157aedc` | текст ошибки/защиты режима поиска |
| `.?AVPERSON_SEARCH_PANEL@@` | `0x014a142c` | `0x018a142c` | RTTI TypeDescriptor-подобная строка |
| `.?AVPLAYER_SEARCH_FILTER_ADVISOR@@` | `0x014a6e2c` | `0x018a6e2c` | RTTI TypeDescriptor-подобная строка |
| `.?AVSCOUT_SEARCH_PERSON_FILTER@@` | `0x014a95a0` | `0x018a95a0` | RTTI TypeDescriptor-подобная строка |

### Структурно подтверждённые кандидаты для классов поиска

RTTI parser связал имена с 32-bit TypeDescriptor → CompleteObjectLocator → ClassHierarchyDescriptor/base array и с candidate vtable pointers. Короткая выборка есть в [`inventory/deep/focused_class_map.csv`](inventory/deep/focused_class_map.csv); полные записи — в [`class_hierarchy_members.csv`](inventory/deep/class_hierarchy_members.csv) и [`rtti_vtable_candidates.csv`](inventory/deep/rtti_vtable_candidates.csv).

| Тип | Direct-base candidate(s) из CHD | Vtable VA candidate(s) / slot 0 target |
|---|---|---|
| `PERSON_SEARCH_PANEL` | `PERSON_LIST_PANEL` | `0x01566dc4` → `0x0099a6a0` (также `0x01566dd0`, `0x01566df8`, `0x01566e0c`) |
| `PERSON_SEARCH_INFO_PANEL` | `CONTAINER` | `0x01566580` → `0x009943d0` (несколько secondary tables) |
| `SCOUT_SEARCH_PERSON_FILTER` | `PERSON_FILTER` | `0x012819a0` → `0x004c5860` (также `0x012819c8`, `0x012819d4`) |
| `PLAYER_SEARCH_FILTER_ADVISOR` | `ADVISOR@SIOS` | `0x015836fc` → `0x00ac1760` (также `0x01583708`, `0x01583730`) |

Для `SCOUT_SEARCH_PERSON_FILTER` vtable candidate в `0x012819a0` slot 1 содержит `0x00ab6a00` — подтверждённое структурой указание на функцию, а не только прежняя гипотеза. Её начало проверено: сохраняет `ESI`, читает byte `[ESI+0x30]`, вызывает predicate/helper-функции и возвращает bool в `AL`; одна из соседних функций `0xab6a30` также возвращает bool. Это сильно поддерживает трактовку как method(s) фильтра объекта, но не доказывает, что данный scout-фильтр подключён к обычным результатам Player Search.

Также подтверждены literal/reference-site кандидаты: `PERSON_SEARCH_PANEL` используется как immediate pointer на instruction sites `0x00479dfa` и `0x004ace6c`; `SCOUT_SEARCH_PERSON_FILTER` — `0x0047b67a`; `PLAYER_SEARCH_FILTER_ADVISOR` — `0x0047cc7a`; UI text `Well-known players...` — `0x0077634a`; scout-mode error string — `0x00a69513`. Первые три sites выглядят как class/type registration/initialization; точную функцию каждого call site нужно сверить в CFG/PDB.

Для трёх ключей поиска совпадают смещения предыдущего разбора и текущего EXE. Это поддерживает гипотезу, что исследовался тот же билд, но прежний временный файл побайтно не сохранён для сравнения.

Другие прежние ориентиры — **только leads**, не доказанные связи с фильтрацией обычного поиска: `0x7762c0` (кандидат на формирование заголовка панели), текст около `0x776348` («Well-known players in your region»), `0x996a20` как кандидат на метод из vtable по `0x127a700`, слот `0x127a748`; TypeDescriptor/vtable-кандидаты `SCOUT_SEARCH_PERSON_FILTER` (file offset `0x14a95a0`, vtable около `0x12819a0`, callback-кандидат `0xab6a00`) и `PLAYER_SEARCH_FILTER_ADVISOR` (RTTI около `0x14a6e2c`, vtable около `0x15836fc`). В этих адресных записях сохраняется конвенция предыдущего анализа; не все значения заново трассированы как VA/RVA. Класс или связь с обычным Player Search не доказаны.

Scout-специфичный кодовый кандидат: около `0xa69505` проверяется `[esi+5] == 3`, иначе формируется `Attempting to assign scout to a non-scout search`; `PERSON_SEARCH::update` около `0xa69f40` требует режим `3`. Это указывает на режим, но не доказывает, что соответствующая ветка ограничивает результаты обычного Player Search.

## 5. Карта подсистем (уровень статического свидетельства)

1. **Региональные правила соревнований.** Экспортируемые функции `*_get_settings`, `*_setup_comps` и соседние группы по странам/регионам — наиболее явный API-кластер. Следующий шаг: сгруппировать экспорты по префиксу, разобрать несколько шаблонных функций, построить граф вызовов.
2. **Футбольная предметная модель.** RTTI-кандидаты включают множество `PERSON`, `PLAYER`, `TEAM`, `COMP`, `MATCH`, `SQUAD`, `TACTIC`, `TRANSFER` и др. В текущем списке встречается строк `PLAYER` — 677, `TEAM` — 583, `MATCH` — 461, `COMP` — 424, `PERSON` — 302, `TRANSFER` — 308. Это простые подстрочные количества в RTTI-списке, не число реальных классов каждого домена.
3. **UI и поиск.** Есть имена панелей/фильтров и строки Player Search/scout; RTTI даёт удобные якоря для дальнейшего связывания vtable, TypeDescriptor, xref-ов и обработчиков. Имена/строки не заменяют control-flow анализ.
4. **Матч/статистика.** `SIM_STATS`, множество RTTI-строк `MATCH` и кодовые фрагменты в `.cave`, работающие с индексами/таблицами/байтовыми значениями. Точная связь этих фрагментов с интерфейсом просмотра статистики пока не доказана.
5. **База/сохранения.** RTTI включает классы с `DATABASE` (124 подстрочных совпадения по текущему фильтру) и типы persistence/data. Это только направление навигации; форматы DB и сохранений в этой работе не анализировались.
6. **Системные слои.** Импорты подтверждают Win32, OpenGL, Winsock, DirectSound и DbgHelp-зависимости. Не делался runtime trace, поэтому нельзя говорить, какие импорты обязательны, опциональны или доступны в конкретной конфигурации ОС.

## 6. Исполняемая секция `.cave` и переходы из `.text`

Это важный дополнительный результат по текущему файлу: в PE есть отдельная 4-КБ исполняемая `.cave`, а сканирование `.text` нашло 15 `E9 rel32` байтовых последовательностей, целящихся в неё. Все перечисленные ниже источники проверены локальной дизассемблировкой как инструкции `jmp` на указанные адреса. Таблица также находится в [`inventory/cave_jmp_candidates.csv`](inventory/cave_jmp_candidates.csv).

**Интерпретация:** такая раскладка совместима с перенаправлением control flow в дополнительный код. Она необычна и заслуживает отдельного происхождения/чистого эталона, но сама по себе не устанавливает автора, дату или цель изменения. В соседних workspace-материалах есть отдельный `inbox/fm_viewstats_patch.zip`; его README называет SHA-256 выше исходным файлом для своего IPS-патча. Это не доказывает, что `.cave` создан тем патчем (его README описывает три другие правки), и тот архив/второй EXE не является предметом настоящей инвентаризации.

| Source VA | Cave VA | Что видно статически / осторожная формулировка |
|---:|---:|---|
| `0x0087b740` | `0x01c04700` | вызывает `0x877e40`, затем при условии вызывает vfunc `[object+0x88]`; результат сравнивает с `0x28`, возможно обнуляет AL; функция/значение неизвестны |
| `0x008d0ac1` | `0x01c04200` | вычисляет `BL-CL`, не даёт результату стать меньше байта `[EAX]`, записывает байт и продолжает в `0x8d0ac9` |
| `0x00a35853` | `0x01c04400` | ветвление по byte-id и таблицам битов в `.cave` (`0x1c04310`–`0x1c04360`), пишет выбранный byte в stack buffer; похоже на классификацию статистических/атрибутных индексов, точное назначение не установлено |
| `0x00a60da0` | `0x01c04800` | при ненулевом аргументе вызывает vfunc `[object+0x88]`; если результат `>= 0x28`, ставит bit 0 в `[ECX+0x1c]`; точный объект/смысл неизвестен |
| `0x00c5eaa0` | `0x01c04500` | ограничивает значение параметра диапазоном `1..10000` и записывает WORD в `[ECX+0x1dc]` |
| `0x00c5ece9` | `0x01c04040` | суммирует EAX+EDX, использует `[ECX+0x1dc]` как нижнюю границу и не допускает значение меньше 1; продолжает в `0xc5ed00` |
| `0x00cae320` | `0x01c04180` | проверяет указатель `[ECX+0xcc]`, индекс `0..79`, две byte-величины `1..100`; в одном случае поднимает входящее значение до найденного значения структуры; семантика поля не установлена |
| `0x00cae3a0` | `0x01c04100` | превращает отрицательный signed byte из аргумента в ноль, затем продолжает в `0xcae3a9` |
| `0x00cb1fe9` | `0x01c042c0` | один из четырёх участков общего кода нормализации WORD-поля `[ESI+0xe]` |
| `0x00cb202e` | `0x01c042c0` | общий helper; сравнивает AX с `[ESI+0xe]`, сохраняет больший, далее ветвится по EBX |
| `0x00cb2073` | `0x01c042c0` | общий helper для того же поля |
| `0x00cb20a2` | `0x01c042c0` | общий helper для того же поля |
| `0x00cd3fd0` | `0x01c04280` | если WORD-параметр меньше `[ECX+0xe]`, заменяет его значением поля; продолжает исходную проверку в `0xcd3fd5` |
| `0x00cfe060` | `0x01c04000` | signed AL при отрицательном значении обнуляется; затем AL прибавляется к byte `[ESI]`, продолжение в `0xcfe065` |
| `0x01018b20` | `0x01c04600` | сравнивает AX с WORD `[ECX+0x1dc]`, при необходимости поднимает AX, записывает EAX как DWORD в `[ECX+0x1dc]` и вызывает vfunc `+0x30` при изменении |

Рядом в `.cave` есть NOP-поля и адреса (`0x1c04080`, в том числе) с кодоподобными байтами; один лишь линейный дизассемблер не устанавливает для них reachable entry point. Внутренний control flow, indirect references, точные границы функций и происхождение кода требуют отдельной проверки. Некоторые обработчики выглядят как нормализация/ограничение чисел или статистических индексов, но без типов/вызовов это только описание операций, не бизнес-смысл.

## 6.1. Расширенные инвентари, RTTI-граф и полный sweep

Для следующего уровня статического разбора добавлен второй генератор [`deep_analysis.py`](deep_analysis.py), требующий `pefile` и `capstone`. Он дополнительно извлекает заголовки/Load Config, debug/PDB-record, метрики секций, binary resource payloads, широкие строки, структуры RTTI, кандидаты на vtable, string-pointer references, IAT-вызовы и результаты дизассемблирования. Основные результаты — в [`inventory/deep/`](inventory/deep/).

### Наиболее полезные дополнительные результаты

- **CodeView/PDB:** одна RSDS-запись, GUID `3C1DEAC9-10D8-4E84-BEC1-8ACEBBCCE806`, age `1`; PDB path указывает на `fm\8.0.2\english\game\builds\win32\release final\application\fm.pdb`. Файл PDB отсутствует, но GUID+age позволяет запросить точные символы.
- **RTTI и иерархии:** найдено 8,154 совпадения `.?AV...@@` / 7,795 уникальных имён; 22,543 aligned pointer-кандидата на TypeDescriptor; 14,296 structurally validated x86 CompleteObjectLocator → ClassHierarchyDescriptor chains; 7,989 различных CHD и 38,667 записей base-class-array. CSV сохраняет типы и offsets/attributes. `rtti_vtable_candidates.csv` содержит 14,296 structurally derived vtable-address candidates. Это существенно лучше простого поиска имён, но всё ещё не полный C++ AST: некоторые адреса/кандидаты требуют сопоставления с методами и отсева совпадающих структур.
- **String/data xrefs:** 45,700 попаданий bytewise absolute-pointer scan на адреса printable strings; это кандидаты, а не 45,700 подтверждённых ссылок из инструкций. Параллельно найдено 1,628 UTF-16LE ASCII-подобных строк, сохранены в `strings_utf16le_ascii.tsv.gz`.
- **Экспортируемые функции:** `export_disassembly.txt` содержит короткий стартовый фрагмент для всех 382 экспортов (максимум 48 инструкций или до первого RET; это не доказанные границы функций). `function_entry_candidates.csv` объединяет exports, entrypoint и CALL targets; из-за linear sweep его 31,361 адрес нельзя считать реальными функциями без ручной валидации. `iat_call_site_candidates.csv` содержит 523 потенциальных `CALL/JMP [absolute IAT]` байтовых места.
- **Полный текстовый дизассемблер:** [`inventory/text_linear_disassembly.asm.gz`](inventory/text_linear_disassembly.asm.gz) — GNU objdump `-D -Mintel` по всем raw bytes `.text`; [`inventory/cave_disassembly.asm`](inventory/cave_disassembly.asm) — `.cave`. Это воспроизводимый линейный sweep, не CFG: `.text` содержит embedded data, поэтому часть инструкций/ветвлений может быть мусорной декодировкой.
- **Capstone control-flow-кандидаты:** [`inventory/deep/linear_control_flow_candidates.csv.gz`](inventory/deep/linear_control_flow_candidates.csv.gz) — 850,872 direct call/jump/conditional candidates из линейного sweep; [`linear_mnemonic_counts.csv`](inventory/deep/linear_mnemonic_counts.csv) — счётчики декодированных mnemonic. Число велико именно потому, что sweep интерпретирует данные как x86. Использовать только как поиск ориентиров, **не** как call graph.
- **Ресурсы:** [`inventory/deep/resource_payloads.csv`](inventory/deep/resource_payloads.csv) даёт SHA-256 каждого из 43 extracted payloads; сами raw payloads в `inventory/deep/resource_payloads/`. В частности, thumbnail распознан как PNG, GDF XML сохранён в исходном UTF-16LE формате; прочие Windows resources оставлены как raw `.bin`.
- **Структура и mitigation:** [`inventory/deep/pe_metadata.json`](inventory/deep/pe_metadata.json), [`debug_directory.csv`](inventory/deep/debug_directory.csv), [`section_entropy.csv`](inventory/deep/section_entropy.csv). Load Config содержит указатели `SecurityCookie` и SafeSEH table/count (`SEHandlerCount=13,314`); `.cave` имеет энтропию около `1.684` bits/byte, что согласуется с большим NOP-fill, но не устанавливает происхождение секции.

### Authenticode: уточнение результата

Проведён PE image digest check: встроенный SHA-1 `6cbea0a5633e6139dd2f70a1fe241dd4b379e279` расходится с вычисленным Authenticode SHA-1 `af461bf88674c836f07cb04c75fed7885d31453d`. Signify выдал `AuthenticodeInvalidDigestError`. Следовательно, встроенный PKCS#7 **не подтверждает текущие байты `fm.exe`**. Вычисление image digest проверяет согласованность подписи с файлом; доверенность корневой цепочки, revocation status и отдельная RSA-подпись PKCS#7 не подтверждались. Для Signify 0.9.3 локально поправлена только regex-совместимость `oscrypto` с системной строкой OpenSSL `3.0.20` (изменение было только в `/tmp`, в репозиторий не переносилось). Подробности записаны в `pe_metadata.json`.

## 7. Сертификат, происхождение и ограничения

- Сертификатный блок содержит signer certificate с субъектом `Sega Europe Limited` и timestamping-цепочку. Текущий PE image digest **не совпадает** с digest в signed content; значит, подписанное значение не соответствует нынешнему файлу. Это совместимо с изменением после подписания, ошибочно собранным контейнером или иным provenance issue, но не определяет автора/дату изменения.
- Проверка цепочки по актуальному доверенному хранилищу, revocation и независимая проверка RSA/CMS signature не выполнены. Поэтому нельзя утверждать, что сертификатная цепочка или сама подпись signer-а валидны.
- Размер/дата ZIP и PE timestamp не устанавливают официальный эталон; соседний `fm_viewstats_patch.zip` называет этот SHA-256 ожидаемым исходником своего патча, но это внутреннее заявление из workspace, не независимый vendor reference.
- Совпадение прежних string offsets с этим файлом — полезный идентификатор, но не побайтное сравнение с прежней временной копией.
- Анализ статический: игра не запускалась, динамическая трассировка, проверка влияния кода на игровые данные и end-to-end-тестирование отсутствуют.
- Полный linear disassembly и flow/xref candidate tables теперь приложены, но это всё ещё не доказанные функции/CFG: проход без символов смешивает код, jump tables и строки/данные. 850,872 control-flow candidates — намеренно широкий набор, большая часть не должна считаться реальными ветвлениями.
- RTTI-иерархии и vtable-кандидаты получены парсером 32-bit MSVC structures и структурными проверками. Они создают полезный граф-кандидат, но не доказывают, что каждый pointer occurrence используется как RTTI at runtime; названия методов и semantic ownership требуют проверки.
- String-pointer cross-reference scan тоже эвристический: 45,700 совпадений raw pointer pattern не равны подтверждённым ссылкам из кода.
- Экспортируемые названия — сильные подсказки к API соревнований, но не формальная спецификация ABI.
- `.cave`/NOP/переходы сами не устанавливают автора/дату изменения. Вместе с несовпадающим Authenticode image digest они дают сильный повод искать чистый эталон и снимать byte-diff; без такого эталона точное происхождение секции/отличий не установлено.

## 8. Что полезно делать следующему аналитику

1. Найти matching PDB по GUID/age `3C1DEAC9-10D8-4E84-BEC1-8ACEBBCCE806` / `1` (или официальный symbol server/архив) и применить точные символы.
2. Найти доверенный чистый release-эталон 8.0.2 и сравнить raw bytes по разделам, особенно `.cave`, подписи/сертификатной области и hooks.
3. Отдельно проверить подпись PKCS#7/CMS и timestamp chain (подпись signer content, сертификаты, доверие и revocation) — независимо от уже установленного mismatch image digest.
4. Для каждого из 15 hooks разобрать обе стороны detour: перезаписанные инструкции, сохранение регистров/stack, continuation и caller-ы; построить локальные CFG с корректной границы функции.
5. Использовать 14,296 RTTI/COL/vtable candidates для сопоставления панелей, фильтров и типов, затем подтвердить xrefы конкретными инструкциями. Для Player Search отдельно связать TypeDescriptor → class hierarchy/vtable → string xrefs → функции фильтрации.
6. Разметить/исключить embedded data, jump tables и padding для качественного `.text` CFG; лишь после этого интерпретировать функцию/ветвь. Не использовать 850k линейных branch candidates как готовый graph.
7. Сгруппировать региональные exports и RTTI домены; вручную сопоставить `SIM_STATS`/stat-фрагменты с match display, не выводя бизнес-смысл только из названий.

## 9. Файлы этого пакета

- [`analyze_fm2008_exe.py`](analyze_fm2008_exe.py) — генератор инвентарей; требуется `pefile`.
- [`inventory/summary.json`](inventory/summary.json) — хэш и основные поля PE.
- [`inventory/sections.csv`](inventory/sections.csv), [`inventory/directories.csv`](inventory/directories.csv) — секции и data directories.
- [`inventory/imports.csv`](inventory/imports.csv), [`inventory/exports.csv`](inventory/exports.csv), [`inventory/resources.csv`](inventory/resources.csv) — полные списки.
- [`inventory/rtti_type_names.txt`](inventory/rtti_type_names.txt) — дедуплицированные RTTI-like имена.
- [`inventory/strings_ascii.tsv.gz`](inventory/strings_ascii.tsv.gz) — все извлечённые ASCII-строки с file offsets.
- [`inventory/key_strings.csv`](inventory/key_strings.csv) — ключевые тематические строки.
- [`inventory/cave_jmp_candidates.csv`](inventory/cave_jmp_candidates.csv) — 15 найденных detour-переходов-кандидатов.
- [`deep_analysis.py`](deep_analysis.py) — генератор расширенного набора; нужны `pefile` + `capstone`.
- [`authenticode_check.py`](authenticode_check.py) — воспроизводимое сравнение SHA-1 из подписанного PE image digest с вычисленным хэшем; проверку сертификатной цепочки не выполняет.
- [`inventory/text_linear_disassembly.asm.gz`](inventory/text_linear_disassembly.asm.gz) и [`inventory/cave_disassembly.asm`](inventory/cave_disassembly.asm) — текстовый дизассемблер `.text` и `.cave`.
- `inventory/deep/` — заголовки, CodeView/PDB, энтропия, export snippets, xref candidates, RTTI/COL/vtable/class-hierarchy CSV, wide strings, compressed flow-candidate list и ресурсные дампы.
- [`inventory/deep/deep_counts.json`](inventory/deep/deep_counts.json) — счётчики расширенных инвентарей и оговорки sweep.
- [`inventory/deep/pe_metadata.json`](inventory/deep/pe_metadata.json) — заголовки/Load Config и вычисленный mismatch Authenticode digest.
- [`inventory/deep/entrypoint_disassembly.txt`](inventory/deep/entrypoint_disassembly.txt) — адресный листинг entrypoint; машинный код, не символизирован.
- [`inventory/deep/class_hierarchy_members.csv`](inventory/deep/class_hierarchy_members.csv), [`rtti_vtable_candidates.csv`](inventory/deep/rtti_vtable_candidates.csv), [`focused_class_map.csv`](inventory/deep/focused_class_map.csv), [`string_pointer_xref_candidates.csv`](inventory/deep/string_pointer_xref_candidates.csv) — основные кандидаты связей.
- [`inventory/deep/rtti_keyword_counts.csv`](inventory/deep/rtti_keyword_counts.csv), [`export_prefix_counts.csv`](inventory/deep/export_prefix_counts.csv) — ориентировочная группировка имён классов и префиксов exports.
- [`inventory/deep/resource_payloads.csv`](inventory/deep/resource_payloads.csv) и каталог `inventory/deep/resource_payloads/` — хэшированные извлечённые ресурсы.
