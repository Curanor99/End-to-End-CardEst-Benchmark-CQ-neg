docker run --name postgres-db \
--memory=16g \
--memory-swap=16g \
--cpus=4 \
-e POSTGRES_PASSWORD=postgres \
-e POSTGRES_USER=postgres \
-e POSTGRES_DB=benchmark \
-p 5432:5432 \
-d postgres:18.6