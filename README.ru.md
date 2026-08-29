# UI Design Workbench

[English](README.md) · [История изменений](CHANGELOG.md)

Превращает UI-код проекта в автономный интерактивный HTML-workbench — без сборки и запуска приложения.

```text
UI-код → кешированная карта → строгий UI IR → интерактивный HTML
```

Помогает понять незнакомый интерфейс, увидеть экраны и навигацию, проверить реконструкцию или отдельно провести UI/UX-ревью.

## Установка

Нужны Python 3.10+ и [`pipx`](https://pipx.pypa.io/).

```sh
pipx install ui-design-workbench-cli
uidw install-skill codex
```

`install-skill` также поддерживает `claude`, `cursor`, `gemini`, `copilot`, `opencode`, `agents` и `all`.

Необязательная локальная MCP-интеграция:

```sh
pipx inject ui-design-workbench-cli "mcp>=2,<3"
```

Проверка установки:

```sh
uidw --version
uidw doctor
```

## Быстрый старт

Один раз выберите детализацию:

```sh
uidw --repo <repo> config setup
```

Соберите и откройте workbench из исходников:

```sh
uidw --repo <repo> workbench --output-dir <artifacts> --level full --open
```

Запускайте UI/UX-аудит только когда нужна продуктовая критика:

```sh
uidw --repo <repo> review --output-dir <review-dir> --level full
```

`workbench` и `check` проверяют проекцию. Только `review` создаёт UI/UX-замечания.

## Возможности

- Карта экранов, маршрутов, компонентов, токенов, тем и состояний.
- Автономный HTML со ссылками на исходники и восстановленной навигацией.
- Инкрементальный анализ только изменившихся UI-файлов.
- Доказательства для свойств и явные пробелы вместо придуманного интерфейса.
- Точечные патчи ревью и отдельный авторизованный apply-шаг для исходников.
- Структурный перенос Android/Apple-ресурсов и поиск доступных путей нативного снимка.

Поддерживаются Web, React, Vue, Svelte, Jetpack Compose, Android Views XML, SwiftUI, Storyboard/XIB, WinUI/WPF и Flutter.

## Основные команды

| Команда | Назначение |
| --- | --- |
| `uidw doctor` | Проверить установку и необязательные зависимости |
| `uidw --repo <repo> context --json` | Получить компактный кешированный контекст |
| `uidw --repo <repo> scope ...` | Подготовить ограниченный контекст экрана или замечания |
| `uidw --repo <repo> patch ...` | Проверить или применить точечные изменения артефакта |
| `uidw --repo <repo> workbench ...` | Собрать и проверить HTML-проекцию |
| `uidw --repo <repo> native status` | Найти нативные Android/Apple-провайдеры без запуска |
| `uidw --repo <repo> check ...` | Повторить проверки без UI/UX-аудита |
| `uidw --repo <repo> review ...` | Явно запустить UI/UX-ревью |
| `uidw --repo <repo> fidelity ...` | Посмотреть доказательства и ограничения адаптеров |
| `uidw --repo <repo> mcp` | Запустить необязательный локальный MCP через stdio |

Подробности: `uidw help overview`, `uidw help advanced` или `uidw <команда> --help`.

## Точность и безопасность

- HTML — статическая проекция исходников, а не доказательство runtime- или pixel-parity.
- Перенос Android и Apple остаётся структурным до появления нативного снимка из тех же исходников.
- Неподдерживаемые bindings, custom drawing, runtime-данные и платформенное поведение остаются явными пробелами.
- Preview и review не меняют исходники приложения; применение предложения — отдельный шаг.
- Производный кеш и состояние ревью по умолчанию хранятся вне целевого репозитория.

## Обновление

```sh
pipx upgrade ui-design-workbench-cli
uidw install-skill codex
```

Windows `.exe` пока не публикуется. Основной кросс-платформенный способ установки — PyPI + `pipx`.

## Документация

- [История изменений](CHANGELOG.md)
- [Интеграции с агентами](references/agent-integrations.md)
- [Контракт точности](references/fidelity.md)
- [Нативный рендеринг](references/native-rendering.md)
- [Протокол кеша](references/cache-protocol.md)
- [Каталог платформенных компонентов](references/component-catalog.md)
- [Схема IR](references/ir-schema.md)
- [Процесс ревью](references/review-workflow.md)

Текущая версия CLI: `0.6.3`.
