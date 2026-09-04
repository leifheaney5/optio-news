# Optio remaining rebuild — execution plan

## Goal

Finish the remaining production path from the supplied Optio Rebuild Plan: durable feeds and articles, clustering, per-user reading state, public entry point, explainable ranking, digest preferences, search/alerts, and a verified Railway deployment.

## Work slices

- [x] Persist the feed catalogue, subscriptions, articles, clusters, reading state, digest preferences, and saved searches.
- [x] Move RSS ingestion and image enrichment into the one-shot worker; keep web requests database-only.
- [x] Add canonical URL deduplication, keyset pagination, clustering, and per-user feed isolation.
- [x] Add read/seen/dismiss state and use it in the reader and ranking API.
- [x] Add public landing, onboarding category selection, personalized scoring, digest unsubscribe, search, alerts, and PWA metadata.
- [x] Add migrations and local verification coverage.
- [x] Deploy the web service and scheduled service to the existing Railway project, configure only non-secret runtime settings, and verify `https://optio.news`.

## Safety boundaries

Do not read or print production secrets or production records. Do not claim live status until the Railway deployment reaches success and the exact public hostname responds with the expected application behavior. Preserve the existing legacy tables during the first migration so current users and bookmarks remain recoverable.
