import { bucket, defineRailway, github, postgres, preserve, project, redis, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Postgres = postgres("Postgres", { region: "us-west2" });
  const Redis = redis("Redis", { region: "us-west2" });
  Redis.deploy = { startCommand: "/bin/sh -c \"rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --save 60 1 --dir $RAILWAY_VOLUME_MOUNT_PATH\"" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 5000 });
  const redisVolume = volume("redis-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 50000 });
  const PostgresPITR = bucket("Postgres-PITR", { region: "sjc" });
  const optioDigest = service("optio-digest", {
    source: github("leifheaney5/optio-news", { checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "python scheduled_job.py",
    preDeploy: "flask --app main db upgrade",
    replicas: { "us-west2": 1 },
    deploy: { cronSchedule: "0 9 * * *", restartPolicyType: "NEVER" },
    env: { DATABASE_URL: preserve(), PUBLIC_BASE_URL: preserve(), SECRET_KEY: preserve() },
  });
  const optioIngest = service("optio-ingest", {
    source: github("leifheaney5/optio-news", { checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "python worker.py",
    preDeploy: "flask --app main db upgrade",
    replicas: { "us-west2": 1 },
    deploy: { cronSchedule: "0 * * * *", restartPolicyType: "NEVER" },
    env: { DATABASE_URL: preserve(), OPTIO_ARTICLE_RETENTION_DAYS: preserve(), PUBLIC_BASE_URL: preserve(), SECRET_KEY: preserve() },
  });
  const optioNews = service("optio-news", {
    source: github("leifheaney5/optio-news", { checkSuites: false }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "sh -c 'gunicorn -w 2 -k gthread --threads 4 --timeout 60 --max-requests 500 --max-requests-jitter 50 -b 0.0.0.0:${PORT:-8080} wsgi:application'",
    preDeploy: "flask --app main db upgrade",
    healthcheck: "/login",
    healthcheckTimeout: 90,
    replicas: { "us-west2": 1 },
    deploy: { sleepApplication: true, restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 3 },
    domains: ["optio.news"],
    env: { DATABASE_URL: preserve(), PORT: preserve(), PUBLIC_BASE_URL: preserve(), RATELIMIT_STORAGE_URI: preserve(), SECRET_KEY: preserve() },
  });

  return project("optio-news-website", {
    resources: [Postgres, optioDigest, Redis, optioIngest, optioNews, postgresVolume, redisVolume, PostgresPITR],
  });
});
