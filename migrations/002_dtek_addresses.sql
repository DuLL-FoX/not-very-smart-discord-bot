CREATE TABLE IF NOT EXISTS dtek_addresses (
    id SERIAL PRIMARY KEY,
    region TEXT NOT NULL,
    city TEXT NOT NULL,
    street TEXT NOT NULL,
    house TEXT NOT NULL,
    label TEXT NOT NULL,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dtek_addresses_guild ON dtek_addresses(guild_id);
CREATE INDEX IF NOT EXISTS idx_dtek_addresses_channel ON dtek_addresses(channel_id);
CREATE INDEX IF NOT EXISTS idx_dtek_addresses_label ON dtek_addresses(guild_id, label);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dtek_addresses_unique_label 
    ON dtek_addresses(guild_id, label);
