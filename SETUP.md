docker run --name postgres-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=benchmark \
  -p 5432:5432 \
  -d postgres:18.6