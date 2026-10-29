# Public sample fixture for XV05 (candidate-visible). Fixed content, no RNG.
lines <- c(
  'ts,user,amount,status',
  '2026-03-01 08:15:00,007,12.50,ok',
  '2026-03-01 08:20:31,"Smith, J",3,ok',
  '2026-03-01 09:02:10,042,n/a,failed',
  '2026-03-02 10:00:00,,7.25,',
  'not a time,123,1e2,ok'
)
writeLines(lines, file.path(Sys.getenv("OUT_DIR", "/out"), "events.csv"))
