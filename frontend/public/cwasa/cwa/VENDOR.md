# Vendored: CWASA runtime

`allcsa.js` (~2.6 MB) and `cwasa.css` are the **CWASA** signing-avatar runtime,
vendored as static assets and served unmodified. SignSpeak loads `allcsa.js` at
runtime via `src/avatar/driver.ts`; `cwasa.css` is intentionally **not** loaded
(its global selectors override the app theme — the rules actually needed are
inlined in `src/index.css`).

## Provenance

- **Project:** CWASA ("CWA SiGML Avatar") / JASigning, the browser SiGML avatar
  from the University of East Anglia (UEA) Virtual Humans research group.
- **Bundle contents:** the CWASA runtime plus third-party libraries, including
  IE polyfills (Rousan Ali, MIT License) and a zip library (Gildas Lormeau,
  BSD-style license) — their copyright notices are retained inline.
- **Version:** not embedded as a static string (the runtime reads its version
  from a `CWASA` global at load time). Record the upstream build here when the
  asset is next refreshed.

## Action required

Confirm and document the **upstream source URL and CWASA license terms** with
UEA before any public release — CWASA/JASigning is research software and is not
distributed under a standard open-source license. Treat this file as the place
to pin that information once verified.
