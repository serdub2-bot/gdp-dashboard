# ECC → Devin: патч совместимости плагина

Патч закрывает ровно то предупреждение, которое вы видите в Devin:

> ⚠ Крючок деформирован — https://github.com/affaan-m/ECC

ECC (affaan-m/ECC) — плагин в формате **Claude Code**: граф хуков лежит в
`hooks/hooks.json` (matcher'ы `Bash` / `Write` / `Edit`, события `PostToolUseFailure`,
`PreCompact`, `async: true`, блокировка через `hookSpecificOutput.permissionDecision:"deny"`).
Devin читает хуки плагина из **корневого `hooks.json`** в своём формате (`hooks.v1`):
свои события (`PostCompaction` вместо `PreCompact`, без `PostToolUseFailure`), свои имена
инструментов (`exec`, `write`, `edit`, …) и свой контракт блокировки (`decision:"block"`).
Формально не совпадает ничего, кроме общего «событие → matcher → hooks[]», поэтому
валидатор Devin и ругается на «деформированный крючок», а сами хуки ECC в Devin не работают.

Патч добавляет три вещи (без изменения существующего `hooks/hooks.json`):

| Файл | Зачем |
|---|---|
| `.devin-plugin/plugin.json` | нативный манифест Devin (без него Devin падает в Claude-совместимый режим и спотыкается о `hooks/hooks.json`) |
| `hooks.json` (в корне) | 6 записей — по одной на событие Devin; все вызовы ведут в диспетчер |
| `hooks/devin/dispatch.mjs` | единственный новый рантайм: выбирает нужные хуки ECC из `hooks/hooks.json`, переводит payload Devin → Claude, запускает их и переводит ответ обратно в контракт Devin |
| `hooks/devin/build-hooks-json.mjs` | генератор `hooks.json` (одна таблица событий, `--check` для CI) |
| `hooks/devin/validate.mjs` | схема + свежесть + дымовые проверки без запуска Devin |

## Что уже проверено (локально, на реальном чекауте ECC)

* `node hooks/devin/validate.mjs` — все проверки проходят;
* `PreToolUse` + `exec` → ECC GateGuard реально блокирует: Devin получает
  `{"decision":"block","reason":"[Fact-Forcing Gate] …"}` (раньше был Claude-формат
  `permissionDecision:"deny"`, который Devin не понимает);
* `PreToolUse` + `git status` → тишина (никаких ложных блокировок), ~120 мс;
* `PostToolUse` + `edit` файла с `console.log` → `additionalContext` с предупреждением ECC;
* `SessionStart` → в контекст попадает блок инициализации ECC (package manager, observer lease);
* `UserPromptSubmit`, `Stop`, `SessionEnd` — без ошибок, 100–460 мс;
* `ECC_HOOKS=0` — полное отключение моста; `PostCompaction`/`PermissionRequest` осознанно не мапятся.

## Как применить

### Быстро: сразу починить у себя (5 минут)

```bash
cd /path/to/ecc-devin-patch
./install-local.sh ~/ecc-devin-plugin      # клонирует ECC, накладывает патч, проверяет

cd ~/ecc-devin-plugin
devin plugins remove ecc                   # убрать версию, установленную из GitHub
devin plugins install --local .            # поставить локальную копию с патчем
devin plugins info ecc                     # в выводе должен появиться блок Hooks
```

Локальный плагин связан с папкой: правите файлы — новая сессия Devin их подхватывает
без переустановки. После этого предупреждение «крючок деформирован» для ECC исчезает,
а его хуки начинают реально срабатывать (проверено: блокировка `rm -rf /`,
предупреждение про `console.log` после `edit`, контекст на `SessionStart`).

### Вручную / в форк

```bash
git clone https://github.com/affaan-m/ECC.git && cd ECC
/path/to/ecc-devin-patch/apply.sh .        # наложить патч
/path/to/ecc-devin-patch/verify.sh .       # проверки
git checkout -b feat/devin-native-plugin
git add -A && git commit -m "feat(devin): native plugin manifest and hooks bridge"
```

Дальше — PR в апстрим (готовое описание: `pr/PR_BODY.md`) и, после мержа,
установка по тегу: это снимет и второе предупреждение — «плагин не закреплён».

## Границы (честно)

* Devin грузит хуки плагина **только в локальных сессиях** (CLI и Desktop) и **best effort /
  fail open** — это его собственные ограничения, не наши. В облачных сессиях и в веб-версии
  хуки не выполняются вообще, там работают только скиллы/правила/субагенты.
* `PreCompact` (ECC сохраняет состояние *до* компакции) не мапится на `PostCompaction`
  (Devin вызывает его *после*) — это была бы неверная семантика, лучше не запускать.
  `PostToolUseFailure` у Devin нет — соответствующие хуки ECC в Devin не срабатывают.
* `async: true` хуки ECC запускаются как detached-процессы (Devin не умеет async-хуки),
  их вывод не влияет на сессию.
* Патч не претендует на то, что все 27 хуков ECC одинаково осмысленны в Devin: смысл в том,
  чтобы они перестали ломать валидатор и работали те, у которых есть прямой аналог.

## Что осталось сделать в самом ECC (для мейнтейнеров)

Помимо файлов патча, в PR стоит добавить Devin в служебные таблицы репозитория:

* `scripts/lib/harness-adapter-compliance.js` — запись `devin` (state: `Adapter-backed`,
  поддерживаемые ассеты: skills/rules/agents/hooks best-effort, source_docs — `.devin-plugin/plugin.json`,
  `hooks/devin/README.md`);
* `scripts/ci/catalog.js` / `scripts/harness-audit.js` — если они перечисляют манифесты по именам;
* `scripts/release.sh` — уже включено в патч (`patches/0001-…`), чтобы версия
  `.devin-plugin/plugin.json` не отставала от остальных манифестов.
