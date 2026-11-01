# Open WebUI 👋

![GitHub stars](https://img.shields.io/github/stars/open-webui/open-webui?style=social)
![GitHub forks](https://img.shields.io/github/forks/open-webui/open-webui?style=social)
![GitHub watchers](https://img.shields.io/github/watchers/open-webui/open-webui?style=social)
![GitHub repo size](https://img.shields.io/github/repo-size/open-webui/open-webui)
![GitHub language count](https://img.shields.io/github/languages/count/open-webui/open-webui)
![GitHub top language](https://img.shields.io/github/languages/top/open-webui/open-webui)
![GitHub last commit](https://img.shields.io/github/last-commit/open-webui/open-webui?color=red)
[![Discord](https://img.shields.io/badge/Discord-Open_WebUI-blue?logo=discord&logoColor=white)](https://discord.gg/5rJgQTnV4s)
[![](https://img.shields.io/static/v1?label=Sponsor&message=%E2%9D%A4&logo=GitHub&color=%23fe8e86)](https://github.com/sponsors/open-webui)

![Окно Open WebUI](./banner.png)

**Open WebUI — это расширяемая ([extensible](https://docs.openwebui.com/features/extensibility/plugin)), насыщенная возможностями и удобная платформа для self-hosted ИИ, предназначенная для работы полностью офлайн.** Она поддерживает различные LLM-раннеры, такие как **Ollama** и **OpenAI-совместимые API**, а также **встроенный inference-engine** для RAG, благодаря чему Open WebUI становится **мощным решением для развёртывания ИИ**.

Увлекаетесь open-source ИИ? [Присоединяйтесь к нашей команде →](https://careers.openwebui.com/)

![Демо Open WebUI](./demo.png)

> [!TIP]
> **Ищете [Enterprise-план](https://docs.openwebui.com/enterprise)?** – **[Свяжитесь с нашей командой продаж прямо сегодня!](https://docs.openwebui.com/enterprise)**

Получите **расширенные возможности**, включая **кастомизацию тем и брендинга**, **поддержку Service Level Agreement (SLA)**, **версии Long-Term Support (LTS)** и **ещё больше!**

Для получения дополнительной информации обязательно ознакомьтесь с нашей [документацией Open WebUI](https://docs.openwebui.com/).

## Ключевые возможности Open WebUI ⭐

- 🚀 **Простая настройка**: Устанавливайте без труда через pip, uv, Docker или Kubernetes (kubectl, kustomize или helm). Для контейнерных развертываний доступны образы с тегами `:ollama` и `:cuda`.

- 🤝 **Широкая интеграция моделей и API**: Подключайте любой OpenAI-совместимый API вместе с локальными моделями Ollama. Укажите URL API на **LMStudio, GroqCloud, Mistral, OpenRouter, vLLM и другие**, чтобы свободно комбинировать провайдеров.

- 🔐 **Тонкая RBAC и группы пользователей**: Администраторы задают роли, группы и права максимально детально, чтобы каждому пользователю был доступ ровно к тому, что нужно. По умолчанию — безопасно, а опыт настраивается под каждую группу.

- 🧩 **Поддержка плагинов**: Расширяйте Open WebUI с помощью **фильтров**, **действий**, **pipe**, **tools** и **skills**. Подключайте внешние сервисы через **MCP**, **MCPO** и **OpenAPI tool servers**. Стройте собственные интеграции, лимиты запросов, сценарии согласования, подключения данных и многое другое.

- 🤖 **Модели и агенты**: Оборачивайте любую базовую модель в пользовательские инструкции, tools и знания, чтобы создавать специализированных агентов. Поддерживаются динамические переменные, контроль доступа по пользователям/группам и импорт готовых пресетов через [Open WebUI Community](https://openwebui.com/).

- 📝 **Заметки**: Отдельное рабочее пространство для контента вне диалогов. Создавайте черновики в расширенном редакторе, используйте ИИ для перезаписи выбранного текста и прикрепляйте заметки к любому чату для полного контекстного внедрения.

- 📢 **Каналы**: Общие пространства в реальном времени, где ваша команда и ИИ-модели работают в одной временной шкале. Помечайте модели, чтобы они готовили или критиковали ответы, с ветками (threads), реакциями, закреплениями и контролем доступа.

- 🧠 **Устойчивая память**: ИИ запоминает факты о вас на протяжении диалогов, перенося контекст из одного чата в следующий.

- ✅ **Живой рабочий процесс и поток сообщений**: Наблюдайте, как ИИ строит ответ и проходит чек-листы в реальном времени. Ставьте сообщения в очередь, пока ИИ ещё отвечает — они отправятся автоматически, когда всё будет готово.

## Исправления и обновления

- **Удалены зависимости Tailwind CSS**: Устранены ошибки сборки, связанные с Tailwind CSS, и заменены на стандартные CSS классы.
- **Восстановлен `.gitignore`**: Обновлён и восстановлен `.gitignore` для корректного исключения файлов и директорий из контроля версий.
- **Обновлены стили**: Все классы Tailwind CSS (`rounded-lg`, `prose-*`, `bg-*`, `text-*` и др.) заменены на стандартные CSS стили.

## Установка и запуск

Для установки и запуска Open WebUI выполните следующие команды:

```bash
# Клонируйте репозиторий
git clone https://github.com/open-webui/open-webui.git
cd open-webui

# Установите зависимости
npm install

# Запустите приложение
npm run dev
```

Для Docker:

```bash
# Соберите и запустите Docker-контейнер
docker-compose up -d --build
```

Для получения дополнительной информации о настройке и использовании Open WebUI, пожалуйста, ознакомьтесь с [документацией](https://docs.openwebui.com/).