CREATE TABLE IF NOT EXISTS users (
    Id INTEGER PRIMARY KEY,
    Reputation INTEGER,
    CreationDate TIMESTAMP,
    Views INTEGER,
    UpVotes INTEGER,
    DownVotes INTEGER
);

CREATE TABLE IF NOT EXISTS posts (
    Id INTEGER PRIMARY KEY,
    PostTypeId SMALLINT,
    CreationDate TIMESTAMP,
    Score INTEGER,
    ViewCount INTEGER,
    OwnerUserId INTEGER,
    AnswerCount INTEGER,
    CommentCount INTEGER,
    FavoriteCount INTEGER,
    LastEditorUserId INTEGER
);

CREATE TABLE IF NOT EXISTS postLinks (
    Id INTEGER PRIMARY KEY,
    CreationDate TIMESTAMP,
    PostId INTEGER,
    RelatedPostId INTEGER,
    LinkTypeId SMALLINT
);

CREATE TABLE IF NOT EXISTS postHistory (
    Id INTEGER PRIMARY KEY,
    PostHistoryTypeId SMALLINT,
    PostId INTEGER,
    CreationDate TIMESTAMP,
    UserId INTEGER
);

CREATE TABLE IF NOT EXISTS comments (
    Id INTEGER PRIMARY KEY,
    PostId INTEGER,
    Score SMALLINT,
    CreationDate TIMESTAMP,
    UserId INTEGER
);

CREATE TABLE IF NOT EXISTS votes (
    Id INTEGER PRIMARY KEY,
    PostId INTEGER,
    VoteTypeId SMALLINT,
    CreationDate TIMESTAMP,
    UserId INTEGER,
    BountyAmount SMALLINT
);

CREATE TABLE IF NOT EXISTS badges (
    Id INTEGER PRIMARY KEY,
    UserId INTEGER,
    Date TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    Id INTEGER PRIMARY KEY,
    Count INTEGER,
    ExcerptPostId INTEGER
);
