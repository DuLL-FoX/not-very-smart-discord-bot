CREATE TABLE IF NOT EXISTS roles (
    user_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    time_assigned TIMESTAMP NOT NULL,
    expiration TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_roles_user_id ON roles(user_id);
CREATE INDEX IF NOT EXISTS idx_roles_expiration ON roles(expiration);

CREATE TABLE IF NOT EXISTS phrases (
    id SERIAL PRIMARY KEY,
    range_key TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_phrases_range_key ON phrases(range_key);

INSERT INTO phrases(range_key, message)
SELECT 'default', '{user_mention}, тебе выпало {random_number}. {bot_mention} записал это в книгу судьбы!'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = 'default' AND message = '{user_mention}, тебе выпало {random_number}. {bot_mention} записал это в книгу судьбы!'
);

INSERT INTO phrases(range_key, message)
SELECT '0', '{user_mention}, тебе выпало 0. Даже {bot_mention} слегка удивлён.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '0' AND message = '{user_mention}, тебе выпало 0. Даже {bot_mention} слегка удивлён.'
);

INSERT INTO phrases(range_key, message)
SELECT '1', '{user_mention}, едва не повезло! Твоя единичка — первый шаг к удаче.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '1' AND message = '{user_mention}, едва не повезло! Твоя единичка — первый шаг к удаче.'
);

INSERT INTO phrases(range_key, message)
SELECT '2-10', 'Сегодня удача на твоей стороне, {user_mention}!'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '2-10' AND message = 'Сегодня удача на твоей стороне, {user_mention}!'
);

INSERT INTO phrases(range_key, message)
SELECT '11-29', '{user_mention}, стабильный результат. Ещё чуть-чуть — и повезёт.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '11-29' AND message = '{user_mention}, стабильный результат. Ещё чуть-чуть — и повезёт.'
);

INSERT INTO phrases(range_key, message)
SELECT '30-49', '{user_mention}, середина — неплохое место для старта.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '30-49' AND message = '{user_mention}, середина — неплохое место для старта.'
);

INSERT INTO phrases(range_key, message)
SELECT '50', '{user_mention}, 50 на 50 — классика судьбы!'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '50' AND message = '{user_mention}, 50 на 50 — классика судьбы!'
);

INSERT INTO phrases(range_key, message)
SELECT '51-65', '{user_mention}, на светлой стороне вероятностей.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '51-65' AND message = '{user_mention}, на светлой стороне вероятностей.'
);

INSERT INTO phrases(range_key, message)
SELECT '66', '{user_mention}, 66 — число магии. Осторожнее!'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '66' AND message = '{user_mention}, 66 — число магии. Осторожнее!'
);

INSERT INTO phrases(range_key, message)
SELECT '67-76', '{user_mention}, почти на вершине. Продолжай!'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '67-76' AND message = '{user_mention}, почти на вершине. Продолжай!'
);

INSERT INTO phrases(range_key, message)
SELECT '77', '{user_mention}, неудачник? Сегодня — да. Завтра — посмотрим.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '77' AND message = '{user_mention}, неудачник? Сегодня — да. Завтра — посмотрим.'
);

INSERT INTO phrases(range_key, message)
SELECT '78-99', '{user_mention}, ты почти у вершины! {random_number} — почти 100.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '78-99' AND message = '{user_mention}, ты почти у вершины! {random_number} — почти 100.'
);

INSERT INTO phrases(range_key, message)
SELECT '100', '{user_mention}, соточка! {bot_mention} аплодирует стоя.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '100' AND message = '{user_mention}, соточка! {bot_mention} аплодирует стоя.'
);

INSERT INTO phrases(range_key, message)
SELECT '101', '{user_mention}, 101 — эскапист. Ты за пределами вероятностей.'
WHERE NOT EXISTS (
    SELECT 1 FROM phrases WHERE range_key = '101' AND message = '{user_mention}, 101 — эскапист. Ты за пределами вероятностей.'
);
