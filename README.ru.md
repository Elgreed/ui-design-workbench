# UI Design Workbench

[English](README.md) · [История изменений](CHANGELOG.md) · [Как выпускать релизы](RELEASING.md)

Превращает UI-код проекта в автономный интерактивный HTML-workbench — без сборки и запуска приложения.

```text
UI-код → кешированная карта → строгий UI IR → интерактивный HTML
```

Инструмент помогает быстро понять незнакомый интерфейс, увидеть экраны и переходы, сравнить предложение с исходным макетом или провести отдельное UI/UX-ревью.

## Что вы получаете

- Повторно используемую карту экранов, маршрутов, компонентов, токенов, тем и состояний.
- Интерактивный HTML-прототип со ссылками на исходники и найденной навигацией.
- Инкрементальный анализ: неизменённые UI-файлы не сканируются повторно.
- Проверяемую реконструкцию: неподдерживаемый код отмечается, а не заменяется догадками.
- Безопасный процесс ревью: исходники проекта не меняются до отдельного apply-шага.

Поддерживаются Web, React, Vue, Svelte, Jetpack Compose, Android Views XML, SwiftUI, Storyboard/XIB, WinUI/WPF, Flutter и React Native.

## Установка

Нужен Python 3.10+. Локальный AI-агент необязателен. Node.js и Chrome/Edge/Chromium также необязательны и нужны только для полных браузерных проверок.

Если `pipx` ещё не установлен, установите его один раз:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

```sh
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

Затем установите CLI и Agent Skill — клонировать репозиторий не нужно:

```sh
pipx install ui-design-workbench-cli
uidw install-skill codex
```

Вместо `codex` можно указать `claude`, `cursor`, `gemini`, `copilot`, `opencode`, `agents` или `all`.

До первой публикации в PyPI тот же пакет можно установить напрямую из ZIP-архива GitHub:

```sh
pipx install "https://github.com/Elgreed/ui-design-workbench/archive/refs/heads/main.zip"
uidw install-skill codex
```

Если нужен локальный MCP:

```sh
pipx inject ui-design-workbench-cli "mcp>=2,<3"
```

Проверьте установку:

```sh
uidw --version
uidw doctor
```

Обновление CLI и установленного skill:

```sh
pipx upgrade ui-design-workbench-cli
uidw install-skill codex
```

Готового Windows `.exe` пока нет: это будущий дополнительный артефакт, а не основной формат пакета. Подробности в [RELEASING.md](RELEASING.md).

## Быстрый старт

Один раз выберите детализацию макета:

```sh
uidw --repo <repo> config setup
```

Соберите и откройте workbench по исходникам:

```sh
uidw --repo <repo> workbench --output-dir <artifacts> --level full --open
```

Откройте один экран или интерактивный прототип:

```sh
uidw --repo <repo> open <artifacts>/ui-preview.html --launch --view single --screen <screen-id>
uidw --repo <repo> open <artifacts>/ui-preview.html --launch --view prototype --screen <screen-id>
```

Запускайте UI/UX-ревью только когда нужны продуктовая оценка и предложения:

```sh
uidw --repo <repo> review --output-dir <review-dir> --level full
```

`workbench` и `check` проверяют реконструкцию. Только `review` запускает UI/UX-аудит.

## Основные команды

| Команда | Назначение |
| --- | --- |
| `uidw doctor` | Проверить установку и необязательные зависимости |
| `uidw --repo <repo> context --json` | Получить компактный кешированный контекст |
| `uidw --repo <repo> workbench ...` | Собрать и проверить HTML-workbench |
| `uidw --repo <repo> check ...` | Повторить проверку без UI/UX-ревью |
| `uidw --repo <repo> review ...` | Явно запустить UI/UX-ревью |
| `uidw --repo <repo> scope ...` | Подготовить контекст одного экрана или замечания |
| `uidw --repo <repo> patch ...` | Проверить или применить точечные изменения артефакта |
| `uidw --repo <repo> fidelity ...` | Посмотреть доказательства и ограничения адаптеров |
| `uidw --repo <repo> mcp` | Запустить необязательный локальный MCP через stdio |

Подробности: `uidw help overview`, `uidw help advanced` или `uidw <команда> --help`.

## Точность и безопасность

- HTML — статическая проекция исходников, а не доказательство работы приложения или pixel parity.
- Неподдерживаемые bindings, custom drawing, runtime-данные и неизвестное платформенное поведение остаются явно отмеченными пробелами.
- Android XML-реконструкция не выполняет Data Binding, custom views, constraints и наследование тем. Для визуального подтверждения нужны Layoutlib, скриншоты эмулятора или golden images.
- Артефакты ревью не разрешают менять исходники. Применение предложения — отдельный явный шаг.
- Производный кеш и состояние ревью по умолчанию хранятся вне целевого репозитория.

## Интеграция с агентами и MCP

Agent Skill учит локальные AI-агенты использовать CLI как детерминированный движок. Для больших ревью `scope` возвращает полный ограниченный контекст, а `patch` принимает только точечные операции — агенту не нужен весь IR.

Необязательный `uidw-mcp` предоставляет те же операции через локальный `stdio`, не открывает порт и не заменяет обычный CLI.

## Документация

- [История изменений](CHANGELOG.md)
- [Выпуск и распространение](RELEASING.md)
- [Интеграции с агентами](references/agent-integrations.md)
- [Контракт точности](references/fidelity.md)
- [Схема IR](references/ir-schema.md)
- [Процесс ревью](references/review-workflow.md)
- [Контракт валидации](references/validation.md)

Версия в разработке: `0.3.5` (ещё не опубликована). См. [CHANGELOG.md](CHANGELOG.md).
