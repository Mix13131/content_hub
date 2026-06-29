# Content Hub: техническое задание

## 1. Назначение проекта

Content Hub - платформа автоматической публикации контента в социальные сети и на сайт.

Пользователь публикует контент один раз в Telegram-канал, после чего система сохраняет публикацию, Telegram metadata медиа и автоматически распространяет запись по выбранным площадкам.

Главная цель - максимально сократить ручную работу при ведении социальных сетей для тематики:

- мебель;
- матрасы;
- интерьер.

Основной пользователь: Юлия Смирнова.

## 2. Принцип работы

Источник правды для контента в MVP - Telegram-канал.

Рабочий поток:

```text
Telegram Channel
  -> Telegram webhook
  -> Content Hub API
  -> PostgreSQL
  -> independent publication queue
  -> Website
  -> Instagram
  -> VK
  -> Facebook via Instagram sync
```

Важное архитектурное правило: публикации по платформам не должны зависеть друг от друга. Если Instagram недоступен, публикация на сайт и в VK должна продолжаться.

## 3. MVP

В MVP входит:

- прием новых постов из Telegram-канала;
- сохранение текста, даты, автора, Telegram Post ID и типа публикации;
- поддержка одного фото, нескольких фото, видео, текста с фото, текста с видео и медиагруппы;
- сохранение Telegram `file_id`, `file_unique_id` и metadata медиа без скачивания файлов;
- создание записей в PostgreSQL;
- независимая очередь публикации по площадкам;
- публикация на сайт в раздел `Новости` или `Блог`;
- публикация в Instagram: фото, видео, карусель, Reels;
- публикация в VK: фото, видео, текст;
- учет Facebook через существующую синхронизацию Instagram -> Facebook, без прямой публикации в Facebook API;
- минимальная админ-панель со списком постов, фильтрами, карточкой публикации, статусами, историей и кнопкой Retry;
- логирование ошибок и ответов внешних API.

В MVP не входит:

- Telegram Stories;
- WhatsApp;
- AI-переписывание текста;
- контент-календарь;
- ручные черновики и согласование;
- сбор бизнес-аналитики из соцсетей.
- скачивание медиа из Telegram и S3-совместимое хранилище.

Эти возможности должны быть заложены в архитектуру, но не реализуются в первом релизе.

## 4. Технологический стек

Backend:

- Python 3.11+;
- FastAPI;
- SQLAlchemy 2.x;
- Alembic;
- PostgreSQL на Neon;
- Dramatiq + Redis для фоновых задач;
- Railway для hosting;
- Pydantic Settings для конфигурации;
- pytest для тестов.

Рекомендуемая схема Railway:

- `web` service: FastAPI;
- `worker` service: Dramatiq worker;
- Redis service;
- Neon PostgreSQL как внешняя БД;
- внешние API credentials только через Railway env vars.

## 5. Основные сущности

### Post

Публикация, полученная из Telegram.

Обязательные поля MVP:

| Поле | Тип | Назначение |
|---|---|---|
| `id` | UUID | внутренний идентификатор |
| `telegram_chat_id` | bigint | идентификатор Telegram-канала |
| `telegram_post_id` | bigint | основной Telegram message_id; для медиагруппы берется первый message_id |
| `telegram_media_group_id` | text, nullable | идентификатор медиагруппы внутри канала |
| `telegram_message_ids` | jsonb | все message_id, связанные с публикацией |
| `telegram_url` | text, nullable | ссылка на исходный пост |
| `text` | text | текст поста или caption |
| `author` | text, nullable | автор или подпись поста в канале |
| `telegram_posted_at` | timestamptz | дата и время исходной публикации в Telegram |
| `post_type` | enum | `text`, `photo`, `video`, `carousel`, `mixed` |
| `photo_count` | int | количество фото |
| `video_count` | int | количество видео |
| `is_public` | boolean | явная видимость поста в публичном API сайта; по умолчанию `false` |
| `source` | enum | в MVP всегда `telegram_channel` |
| `status` | enum | общий статус обработки |
| `website_status` | enum | статус сайта |
| `instagram_status` | enum | статус Instagram |
| `facebook_status` | enum | статус Facebook via Instagram sync |
| `vk_status` | enum | статус VK |
| `story_status` | enum, nullable | резерв под Telegram Stories |
| `published_at` | timestamptz, nullable | время полной или частичной публикации |
| `created_at` | timestamptz | время создания записи |
| `updated_at` | timestamptz | время последнего изменения |

Уникальность:

- `telegram_chat_id + telegram_post_id` уникальны;
- `telegram_chat_id + telegram_media_group_id` уникальны для медиагрупп, если `telegram_media_group_id` заполнен.

### Media

Медиафайл, связанный с публикацией.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | UUID | внутренний идентификатор |
| `post_id` | UUID FK | ссылка на Post |
| `type` | enum | `photo`, `video` |
| `file_url` | text, nullable | резерв под будущий публичный или CDN URL файла |
| `storage_key` | text, nullable | резерв под будущий путь в bucket |
| `telegram_file_id` | text | Telegram file_id |
| `telegram_file_unique_id` | text, nullable | устойчивый Telegram file_unique_id |
| `sort_order` | int | порядок медиа в посте |
| `mime_type` | text, nullable | MIME тип |
| `size_bytes` | bigint, nullable | размер файла |
| `width` | int, nullable | ширина изображения/видео |
| `height` | int, nullable | высота изображения/видео |
| `duration_seconds` | int, nullable | длительность видео |
| `created_at` | timestamptz | время сохранения |

### PublicationJob

Отдельная задача публикации на одну площадку.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | UUID | идентификатор задачи |
| `post_id` | UUID FK | публикация |
| `platform` | enum | `website`, `instagram`, `facebook`, `vk`, `telegram_story`, `whatsapp` |
| `status` | enum | `Waiting`, `Publishing`, `Success`, `Error`, `Retry` |
| `attempt_count` | int | количество попыток |
| `max_attempts` | int | лимит попыток |
| `next_retry_at` | timestamptz, nullable | время следующего повтора |
| `external_post_id` | text, nullable | ID записи во внешней системе |
| `external_url` | text, nullable | ссылка на опубликованную запись |
| `last_error_code` | text, nullable | код последней ошибки |
| `last_error_message` | text, nullable | текст последней ошибки |
| `last_api_response` | jsonb, nullable | последний ответ API |
| `created_at` | timestamptz | время создания |
| `started_at` | timestamptz, nullable | время старта последней попытки |
| `finished_at` | timestamptz, nullable | время завершения |

Одна публикация может иметь несколько задач. Ошибка одной задачи не блокирует остальные.

Уникальность:

- `post_id + platform` уникальны.

### PublicationLog

Журнал технических и пользовательских событий.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | UUID | идентификатор события |
| `post_id` | UUID FK, nullable | публикация |
| `job_id` | UUID FK, nullable | задача публикации |
| `service` | text | `telegram`, `storage`, `website`, `instagram`, `facebook`, `vk`, `queue`, `admin` |
| `level` | enum | `info`, `warning`, `error` |
| `event` | text | тип события |
| `message` | text | человекочитаемое описание |
| `error_text` | text, nullable | текст ошибки |
| `api_response` | jsonb, nullable | ответ внешнего API |
| `created_at` | timestamptz | время события |

## 6. Статусы

Статусы публикации по каждой площадке:

- `Waiting` - задача создана и ожидает выполнения;
- `Publishing` - идет публикация;
- `Success` - публикация завершена успешно;
- `Error` - публикация завершилась ошибкой и больше не будет повторяться автоматически;
- `Retry` - публикация ожидает повторной попытки.

Общий `posts.status`:

- `received` - webhook принят;
- `saving_media` - резерв под будущую обработку файлов медиа;
- `saved` - пост и metadata медиа сохранены;
- `queued` - задачи публикации созданы;
- `partially_published` - хотя бы одна площадка успешна, но есть ошибки или ожидание;
- `published` - все включенные площадки успешны;
- `error` - критическая ошибка на этапе приема или сохранения.

## 7. Telegram ingestion

Content Hub принимает обновления через Telegram webhook.

Требования:

- бот должен быть добавлен в Telegram-канал и иметь права, достаточные для получения channel posts;
- webhook должен принимать `channel_post` и `edited_channel_post`;
- система должна проверять секрет webhook-запроса;
- повторные webhook-запросы не должны создавать дубли;
- медиагруппа должна собираться в одну публикацию;
- порядок медиа должен сохраняться;
- текст берется из `text` или `caption`; для медиагруппы приоритет у caption первого элемента, где он заполнен;
- исходные Telegram `file_id` сохраняются;
- после сохранения Post и Media metadata создаются независимые задачи публикации.

Обработка медиагруппы:

1. Приходит несколько update с одинаковым `media_group_id`.
2. Система временно буферизует элементы группы.
3. После короткой задержки сборки, например 3-10 секунд, создает один Post.
4. Первое сообщение группы становится `telegram_post_id`.
5. Все message_id сохраняются в `telegram_message_ids`.

## 8. Media metadata

В MVP медиа не скачиваются из Telegram и не сохраняются в S3-compatible storage.

Content Hub хранит только Telegram metadata:

- `telegram_file_id`;
- `telegram_file_unique_id`;
- тип медиа;
- порядок;
- MIME type;
- размер, если он пришел от Telegram;
- ширину, высоту и длительность видео;
- ссылку на исходный Telegram-пост.

Требования:

- повторная обработка webhook не должна создавать дубли Media;
- `file_url` и `storage_key` остаются nullable и в MVP не заполняются;
- Telegram остается источником медиа для MVP;
- если в будущем понадобится storage, storage key должен быть стабильным и не конфликтовать при повторном webhook;
- рекомендуемый будущий формат ключа:

```text
telegram/{telegram_chat_id}/{telegram_post_id}/{sort_order}_{telegram_file_unique_id}.{ext}
```

- для будущей публикации в Instagram и VK может понадобиться внешний URL медиа;
- если в будущем используется signed URL, срок жизни должен покрывать всю публикацию и retries.

## 9. Publication queue

После успешного сохранения Post и Media создаются независимые задачи:

- `publish_website(post_id)`;
- `publish_instagram(post_id)`;
- `publish_vk(post_id)`;
- `mark_facebook_via_instagram(post_id)`.

Для Telegram Stories и WhatsApp задачи в MVP не создаются, но интерфейс publisher adapter должен их предусматривать.

Правила:

- каждая задача работает независимо;
- DB-only `PublicationStatusService` управляет переходами статусов без запуска worker и без вызова внешних publisher API;
- задача сначала ставит свой статус в `Publishing`;
- при успехе сохраняет `external_post_id`, `external_url`, `last_api_response` и статус `Success`;
- при временной ошибке ставит `Retry` и `next_retry_at`;
- при исчерпании попыток ставит `Error`;
- ручной Retry из админки создает новую попытку и пишет событие в `PublicationLog`;
- worker должен быть идемпотентным: если внешняя публикация уже создана, повтор не должен создавать дубль.

Рекомендуемая стратегия retries:

- максимум 5 попыток;
- задержки: 1 минута, 5 минут, 15 минут, 1 час, 3 часа;
- ошибки авторизации и валидации медиа сразу переводятся в `Error`;
- сетевые ошибки и rate limits переводятся в `Retry`.

## 10. Website

Нужно создать публичный раздел:

- `Новости`; или
- `Блог`.

MVP может быть реализован как серверный раздел FastAPI с шаблонами или как API для уже существующего сайта. Если отдельного сайта нет, базовая реализация должна включать:

- `GET /news` - список публикаций;
- `GET /news/{slug}` - страница публикации;
- `GET /api/posts/public` - JSON для фронтенда сайта.
- `GET /api/posts/public/{post_id}` - публичная карточка публикации для фронтенда сайта.

В текущей реализации публичный API сайта read-only и не требует admin token. Публичными считаются только посты с `is_public = true` и `status != error`. Новый Telegram-пост создается с `is_public = false` и становится видимым только после действия администратора. Публичный JSON возвращает `is_public`, а медиа остаются metadata-only: Telegram `file_id`, `file_unique_id` и `storage_key` не возвращаются, `file_url` пока `null`.

Каждая публикация на сайте должна показывать:

- дату;
- текст;
- фото;
- видео;
- карусель, если медиа несколько;
- ссылку на исходный Telegram-пост.

SEO-задел:

- `slug`;
- `title`;
- `meta_description`;
- `image_alt_text`.

В MVP эти поля можно генерировать простыми правилами, а в будущем передать AI-модулю.

## 11. Instagram

Нужно поддержать:

- одно фото;
- несколько фото как carousel;
- видео;
- видео как Reels, если это основной формат аккаунта;
- фото + текст;
- видео + текст;
- caption из текста Telegram-поста.

Требования:

- аккаунт должен быть подготовлен для официального Instagram publishing API;
- медиа URL должен быть доступен Meta API из интернета;
- adapter должен валидировать типы, размеры и форматы до отправки;
- создание контейнера и публикация должны логироваться как отдельные шаги;
- при ошибке Instagram не блокирует Website и VK;
- успешная публикация Instagram запускает обновление статуса Facebook via Instagram sync.

## 12. Facebook

Прямая публикация в Facebook не входит в MVP.

Используется существующая синхронизация Instagram -> Facebook.

Правила:

- отдельный Facebook API adapter в MVP не реализуется;
- `facebook_status` обновляется на основании результата Instagram-публикации и настройки синхронизации;
- в логах должно быть явно указано, что Facebook опубликован через Instagram sync, а не через прямой API;
- если Instagram публикация не удалась, Facebook не считается опубликованным.

Ограничение: если бизнесу нужна строгая проверка фактического появления поста в Facebook, это отдельный этап с прямой интеграцией Meta/Facebook API или ручной проверкой.

## 13. VK

Нужно поддержать:

- текстовый пост;
- пост с одним фото;
- пост с несколькими фото;
- пост с видео;
- текст + медиа.

Требования:

- adapter должен загружать медиа в VK и затем публиковать запись на стену сообщества;
- ID сообщества и токены хранятся только в env/secret storage;
- внешний `external_post_id` и ссылка на пост сохраняются в `PublicationJob`;
- ошибки токена, прав, формата или загрузки медиа пишутся в `PublicationLog`;
- ошибка VK не блокирует Website и Instagram.

Перед разработкой VK-интеграции нужно отдельно проверить тип токена и разрешения для нужного сообщества, потому что права на публикацию текста и загрузку медиа могут отличаться.

## 14. Telegram Stories

Не входит в MVP.

Архитектурный задел:

- платформа `telegram_story` добавляется в enum платформ;
- `story_status` хранится в Post как nullable поле;
- создается интерфейс `PublisherAdapter`, который позволит позже добавить `TelegramStoryPublisher`;
- в админке MVP показывается пометка `не входит в MVP`, без кнопки публикации.

## 15. WhatsApp

Не входит в MVP.

Архитектурный задел:

- платформа `whatsapp` добавляется в enum платформ;
- для будущего этапа нужен отдельный тип контента: broadcast, status или business message;
- в MVP не создаются jobs и не хранятся пользовательские контакты WhatsApp.

## 16. Admin panel

Минимальная админ-панель должна быть закрыта авторизацией.

Разделы:

- `Посты`;
- список публикаций;
- фильтры;
- карточка публикации;
- история публикации;
- Retry.

Фильтры:

- опубликовано;
- ошибка;
- ожидание;
- платформа;
- дата;
- тип поста.

Список публикаций должен показывать:

- дату;
- превью медиа;
- короткий текст;
- общий статус;
- статусы Website, Instagram, Facebook, VK;
- количество фото;
- количество видео;
- кнопку открытия карточки.

Карточка публикации должна показывать:

- все медиа в правильном порядке;
- полный текст;
- исходную ссылку Telegram;
- статус по каждой соцсети;
- внешние ссылки на опубликованные записи;
- историю попыток публикации;
- последние ошибки;
- кнопку `Retry` по отдельной платформе;
- кнопку `Retry all failed`.

## 17. API endpoints

MVP endpoints:

| Endpoint | Метод | Назначение |
|---|---|---|
| `/webhooks/telegram` | POST | прием Telegram updates |
| `/healthz` | GET | health check |
| `/admin/jobs` | GET | временный API список publication jobs |
| `/admin/jobs/{job_id}` | GET | временный API карточка publication job с логами |
| `/admin/jobs/{job_id}/start` | POST | временный API старт job |
| `/admin/jobs/{job_id}/success` | POST | временный API отметить успех job |
| `/admin/jobs/{job_id}/error` | POST | временный API отметить ошибку job |
| `/admin/jobs/{job_id}/retry` | POST | временный API ручной retry job |
| `/admin/jobs/{job_id}/run` | POST | ручной запуск job через Connector Engine |
| `/admin/posts` | GET | read-only список публикаций с фильтрами |
| `/admin/posts/{post_id}` | GET | read-only карточка публикации с Media, Jobs и Logs |
| `/admin/posts/{post_id}/publish` | POST | открыть публикацию в публичном API сайта |
| `/admin/posts/{post_id}/unpublish` | POST | скрыть публикацию из публичного API сайта |
| `/admin/posts/{post_id}/run/{platform}` | POST | ручной запуск job площадки через Connector Engine |
| `/admin/posts/{post_id}/retry/{platform}` | POST | повтор публикации на платформу |
| `/admin/posts/{post_id}/retry-failed` | POST | повтор всех неуспешных платформ |
| `/news` | GET | публичный список новостей |
| `/news/{slug}` | GET | публичная страница новости |
| `/api/posts/public` | GET | публичный JSON для сайта |
| `/api/posts/public/{post_id}` | GET | публичная карточка публикации для сайта |

Внутренние сервисы:

- `TelegramIngestionService`;
- `ConnectorEngine`;
- `PublicationQueueService`;
- `WebsitePublisher`;
- `InstagramPublisher`;
- `VkPublisher`;
- `FacebookSyncMarker`;
- `PublicationStatusService`.

## 18. Publisher adapter contract

Каждая площадка должна реализовывать общий контракт:

```python
class PublisherAdapter:
    platform: str

    async def validate(self, post: Post, media: list[Media]) -> None:
        ...

    async def publish(self, post: Post, media: list[Media]) -> PublishResult:
        ...

    async def retry(self, job: PublicationJob) -> PublishResult:
        ...
```

`PublishResult`:

- `external_post_id`;
- `external_url`;
- `raw_response`;
- `published_at`;
- `warnings`.

Это позволит позже добавить Pinterest, YouTube Shorts, TikTok, Telegram Stories и WhatsApp без переписывания очереди.

## 19. AI-задел

AI не входит в MVP, но архитектура должна поддерживать будущие варианты текста.

Будущие функции:

- переписать текст под каждую соцсеть;
- сделать длинную и короткую версии;
- сгенерировать хэштеги;
- придумать заголовок;
- написать SEO-текст для сайта;
- создать alt-тексты для изображений.

Рекомендуемая будущая таблица `content_variants`:

| Поле | Назначение |
|---|---|
| `id` | идентификатор |
| `post_id` | ссылка на исходный Post |
| `platform` | площадка |
| `variant_type` | `caption`, `title`, `seo`, `hashtags`, `alt_text` |
| `content` | текст варианта |
| `status` | `draft`, `approved`, `rejected`, `published` |
| `generated_by` | `manual`, `ai` |
| `created_at` | дата создания |

Правило для будущего AI: AI предлагает варианты, но запись в публикацию происходит только после сохранения утвержденной версии или включения отдельного автоправила.

## 20. Планировщик и черновики

Не входит в MVP, но модель должна не мешать будущим режимам:

- опубликовать сейчас;
- через час;
- завтра;
- по расписанию;
- сохранить как Draft.

Будущие поля:

- `posts.scheduled_at`;
- `posts.publish_mode`: `now`, `scheduled`, `draft`;
- `publication_jobs.not_before`;
- `content_calendar` для недельного и месячного плана.

## 21. Аналитика

Не входит в MVP.

Будущие метрики:

- количество публикаций;
- успешность публикаций;
- ошибки API по сервисам;
- среднее время публикации;
- самые активные дни;
- доля повторных попыток;
- площадки с наибольшим количеством ошибок.

В MVP нужно только хранить достаточно событий в `PublicationLog`, чтобы позже собрать аналитику без миграции истории.

## 22. Безопасность

Требования:

- все токены и ключи только в env/secret storage;
- Telegram webhook проверяет secret token;
- админ-панель закрыта логином;
- API Retry доступен только авторизованному администратору;
- логи не должны показывать полные токены;
- внешние API responses можно хранить, но секретные заголовки и access tokens нужно вычищать;
- public media URLs не создаются в MVP; если storage появится позже, доступность URL и signed URLs должны быть рассчитаны осознанно.

## 23. Ошибки и восстановление

Система должна корректно обрабатывать:

- повторный Telegram webhook;
- неполную медиагруппу;
- недоступность Redis;
- недоступность отдельной соцсети;
- истекший токен платформы;
- неподдерживаемый формат видео;
- ошибку публикации одного элемента карусели;
- ручной повтор публикации после исправления токена или формата.

При критической ошибке приема:

- Post переводится в `error`;
- jobs не создаются;
- админ видит причину.

При ошибке площадки:

- ошибается только соответствующий `PublicationJob`;
- остальные jobs продолжают выполнение.

## 24. Тестирование

Минимальный набор тестов:

- unit: нормализация Telegram text/photo/video updates;
- unit: сбор медиагруппы в один Post;
- unit: idempotency повторного webhook;
- unit: расчет `post_type`, `photo_count`, `video_count`;
- unit: Media metadata extraction для фото и видео;
- unit: platform status transitions;
- integration: Post + Media creation in PostgreSQL;
- integration: job creation after successful Post + Media metadata save;
- integration: failure isolation между Instagram и VK;
- integration: Retry создает новую попытку и пишет log;
- smoke: `/healthz`;
- smoke: `/webhooks/telegram` with fixture;
- smoke: admin posts list;
- smoke: public news page.

Для внешних API в тестах использовать fake adapters. Реальные Instagram/VK calls должны запускаться только в отдельном staging smoke с тестовыми аккаунтами.

## 25. Acceptance criteria

MVP считается готовым, если:

1. Новый текстовый пост в Telegram сохраняется в БД и появляется в админке.
2. Пост с одним фото создает одну Media metadata запись без скачивания файла.
3. Пост с несколькими фото сохраняется как один Post с несколькими Media metadata в правильном порядке.
4. Пост с видео сохраняет видео и корректно определяет `post_type`.
5. Медиагруппа не создает дубли при повторных Telegram webhook.
6. После сохранения создаются независимые jobs для Website, Instagram, VK и Facebook via Instagram sync.
7. Ошибка Instagram не мешает публикации Website и VK.
8. Ошибка VK не мешает публикации Website и Instagram.
9. Website показывает публикацию с датой, текстом, медиа и ссылкой на Telegram.
10. Instagram adapter публикует поддерживаемые фото/видео/карусельные посты или пишет понятную ошибку.
11. VK adapter публикует поддерживаемые фото/видео/текстовые посты или пишет понятную ошибку.
12. Facebook напрямую не вызывается; статус объясняет синхронизацию через Instagram.
13. Админ может нажать `Retry` для отдельной площадки.
14. В логах есть время, сервис, ошибка, текст ошибки и ответ API.
15. Токены не попадают в UI и логи.

## 26. Риски

| Риск | Что сделать |
|---|---|
| Telegram бот не получает посты канала | проверить права бота и allowed updates до разработки |
| Медиагруппа приходит несколькими webhook | добавить буферизацию и idempotency |
| Instagram API не принимает формат видео | сделать preflight validation и понятную ошибку |
| Meta account не готов к publishing API | провести discovery доступа до оценки сроков |
| Facebook sync нельзя подтвердить API | явно показать статус `via Instagram sync` |
| VK токен публикует текст, но не загружает медиа | отдельно проверить права токена на staging |
| Внешним API нужен URL медиа, а MVP хранит только Telegram metadata | перед Instagram/VK этапом отдельно решить, нужен ли storage или другой способ передачи медиа |
| Повторный Retry создает дубли | хранить external IDs и делать adapter idempotent |

## 27. Рекомендуемая структура репозитория

```text
app/
  main.py
  settings.py
  db.py
  models/
    post.py
    media.py
    publication_job.py
    publication_log.py
  schemas/
  services/
    telegram_ingestion.py
    publication_queue.py
    status_service.py
  publishers/
    base.py
    website.py
    instagram.py
    facebook_sync.py
    vk.py
  workers.py
  admin/
  public/
alembic/
tests/
  fixtures/
```

## 28. Этапы разработки

### Этап 0. Access discovery

- получить Telegram bot token;
- добавить бота в канал;
- проверить получение `channel_post`;
- подготовить Neon;
- подготовить Railway;
- проверить доступы Instagram/Meta;
- проверить доступы VK.

### Этап 1. Core ingestion

- FastAPI app;
- PostgreSQL models;
- Alembic migrations;
- Telegram webhook;
- idempotency;
- сохранение Post;
- базовая админка списка.

### Этап 2. Media metadata

- Media records;
- поддержка фото, видео и медиагрупп;
- metadata failure handling.

### Этап 3. Queue

- Redis + Dramatiq;
- PublicationJob;
- независимые jobs;
- retries;
- logs;
- ручной Retry.

### Этап 4. Website

- public news/blog page;
- карточка публикации;
- медиа-рендеринг;
- Telegram link.

### Этап 5. Instagram + Facebook sync

- Instagram publisher;
- status polling/logging;
- Facebook sync marker;
- ошибки и retries.

### Этап 6. VK

- VK publisher;
- загрузка медиа;
- публикация записи;
- errors/retries.

### Этап 7. Stabilization

- smoke tests;
- staging with test accounts;
- production deploy;
- documentation for admin usage.

## 29. Вопросы перед стартом разработки

1. Какой сайт должен получать раздел `Новости`/`Блог`: новый FastAPI-раздел или уже существующий сайт?
2. Есть ли у Instagram аккаунта Business/Creator статус и связь с Facebook Page?
3. Нужно ли публиковать все Telegram-посты автоматически или нужен фильтр/тег для отбора?
4. Нужно ли исключать какие-то посты, например личные, служебные или рекламные?
5. Нужно ли на следующем этапе добавлять storage для внешних соцсетей или достаточно Telegram metadata?
6. Нужна ли модерация перед публикацией в Instagram/VK или сразу автоматическая публикация?
7. Какой VK объект используется: личная страница или сообщество?
8. Что считать успехом Facebook: успешный Instagram post при включенной синхронизации или отдельная проверка Facebook?

## 30. Внешние API-ориентиры

- Telegram Bot API: channel posts and media groups: https://core.telegram.org/bots/api
- Instagram Content Publishing API: single image, video, Reels and carousel publishing through Meta: https://developers.facebook.com/docs/instagram-platform/content-publishing/
- VK API: wall publishing and media upload should be verified against the exact community token and current VK API schema before implementation: https://github.com/VKCOM/vk-api-schema
