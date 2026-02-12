-- Схема БД краудсорсинга стратегий обхода DPI
-- Запускать при первом деплое: psql $DATABASE_URL -f init.sql

-- Таблица стратегий
CREATE TABLE IF NOT EXISTS strategies (
    id              BIGSERIAL PRIMARY KEY,
    provider_id     VARCHAR(50)  NOT NULL,
    service_id      VARCHAR(100) NOT NULL,
    zapret_args     JSONB        NOT NULL,
    strategy_hash   VARCHAR(64)  NOT NULL,
    success_count   INTEGER      NOT NULL DEFAULT 1,
    fail_count      INTEGER      NOT NULL DEFAULT 0,
    avg_latency_ms  REAL         DEFAULT 0.0,
    last_confirmed  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    first_reported  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    status          VARCHAR(20)  NOT NULL DEFAULT 'unconfirmed',

    CONSTRAINT uq_strategy UNIQUE (provider_id, service_id, strategy_hash)
);

CREATE INDEX IF NOT EXISTS idx_strategies_lookup
    ON strategies (provider_id, service_id, status);
CREATE INDEX IF NOT EXISTS idx_strategies_last_confirmed
    ON strategies (last_confirmed);

-- Таблица отчётов (для rate limiting и аналитики)
CREATE TABLE IF NOT EXISTS reports (
    id              BIGSERIAL PRIMARY KEY,
    strategy_id     BIGINT       REFERENCES strategies(id) ON DELETE CASCADE,
    fingerprint     VARCHAR(64)  NOT NULL,
    reported_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    success         BOOLEAN      NOT NULL DEFAULT TRUE,
    latency_ms      REAL         DEFAULT 0.0,
    client_version  VARCHAR(20)  DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_reports_fingerprint_time
    ON reports (fingerprint, reported_at);
CREATE INDEX IF NOT EXISTS idx_reports_strategy
    ON reports (strategy_id);

-- Каталог сервисов
CREATE TABLE IF NOT EXISTS services_catalog (
    id              VARCHAR(100) PRIMARY KEY,
    display_name    VARCHAR(200) NOT NULL,
    category        VARCHAR(50)  NOT NULL,
    main_domain     VARCHAR(200) NOT NULL,
    icon_emoji      VARCHAR(10)  DEFAULT '',
    domains         JSONB        NOT NULL DEFAULT '[]',
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Начальное сидирование каталога сервисов
INSERT INTO services_catalog (id, display_name, category, main_domain, icon_emoji, domains) VALUES
    ('youtube',   'YouTube',    'video',     'youtube.com',              '', '["youtube.com","youtu.be","googlevideo.com","ytimg.com","yt3.ggpht.com","music.youtube.com","studio.youtube.com"]'),
    ('discord',   'Discord',    'messenger', 'discord.com',              '', '["discord.com","discord.gg","discordapp.com","discordcdn.com","cdn.discordapp.com","media.discordapp.net"]'),
    ('instagram', 'Instagram',  'social',    'instagram.com',            '', '["instagram.com","cdninstagram.com","i.instagram.com","graph.instagram.com"]'),
    ('twitter',   'Twitter/X',  'social',    'x.com',                    '', '["x.com","twitter.com","t.co","twimg.com","pbs.twimg.com","video.twimg.com"]'),
    ('facebook',  'Facebook',   'social',    'facebook.com',             '', '["facebook.com","fbcdn.net","fb.com","fb.me","graph.facebook.com"]'),
    ('twitch',    'Twitch',     'video',     'twitch.tv',                '', '["twitch.tv","ttvnw.net","jtvnw.net","clips.twitch.tv","api.twitch.tv"]'),
    ('tiktok',    'TikTok',     'social',    'tiktok.com',               '', '["tiktok.com","tiktokcdn.com","byteoversea.com","musical.ly"]'),
    ('telegram',  'Telegram',   'messenger', 'telegram.org',             '', '["telegram.org","t.me","telegram.me","web.telegram.org"]'),
    ('whatsapp',  'WhatsApp',   'messenger', 'whatsapp.com',             '', '["whatsapp.com","web.whatsapp.com","whatsapp.net"]'),
    ('steam',     'Steam',      'gaming',    'store.steampowered.com',   '', '["steampowered.com","steamcommunity.com","steamstatic.com","store.steampowered.com"]'),
    ('chatgpt',   'ChatGPT',    'ai',        'chatgpt.com',              '', '["chatgpt.com","chat.openai.com","openai.com","api.openai.com","cdn.oaistatic.com"]'),
    ('spotify',   'Spotify',    'other',     'spotify.com',              '', '["spotify.com","scdn.co","open.spotify.com","api.spotify.com"]'),
    ('linkedin',  'LinkedIn',   'social',    'linkedin.com',             '', '["linkedin.com","licdn.com","static.licdn.com","platform.linkedin.com"]'),
    ('github',    'GitHub',     'ai',        'github.com',               '', '["github.com","github.io","githubusercontent.com","api.github.com"]'),
    ('rutracker', 'Rutracker',  'other',     'rutracker.org',            '', '["rutracker.org","rutracker.net","rutracker.cc"]')
ON CONFLICT (id) DO NOTHING;
