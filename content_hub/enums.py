from enum import StrEnum


class PostStatus(StrEnum):
    received = "received"
    saving_media = "saving_media"
    saved = "saved"
    queued = "queued"
    partially_published = "partially_published"
    published = "published"
    error = "error"


class PlatformStatus(StrEnum):
    Waiting = "Waiting"
    Publishing = "Publishing"
    Success = "Success"
    Error = "Error"
    Retry = "Retry"


class PostType(StrEnum):
    text = "text"
    photo = "photo"
    video = "video"
    carousel = "carousel"
    mixed = "mixed"


class ContentSource(StrEnum):
    telegram_channel = "telegram_channel"
    telegram_chat = "telegram_chat"


class MediaType(StrEnum):
    photo = "photo"
    video = "video"


class PublicationPlatform(StrEnum):
    website = "website"
    instagram = "instagram"
    facebook = "facebook"
    vk = "vk"
    telegram_story = "telegram_story"
    whatsapp = "whatsapp"


class PublicationLogLevel(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"
