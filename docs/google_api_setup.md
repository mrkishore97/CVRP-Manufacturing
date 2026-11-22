# Google Maps Platform setup and restrictions

This app uses Google Maps Platform only from the backend. Do not place Google API
keys in Streamlit code, frontend session state, uploaded files, sample data,
exports, or build logs.

Official references, last checked on 2026-11-22 for Version 1.1:

- [Google Maps Platform security guidance](https://developers.google.com/maps/api-security-best-practices)
- [Routes API overview](https://developers.google.com/maps/documentation/routes)
- [Compute Route Matrix overview](https://developers.google.com/maps/documentation/routes/compute-route-matrix-over)
- [Compute Route Matrix request guide](https://developers.google.com/maps/documentation/routes/compute_route_matrix)
- [Geocoding API overview](https://developers.google.com/maps/documentation/geocoding/guides-v3/overview)
- [Geocoding API setup](https://developers.google.com/maps/documentation/geocoding/guides-v3/get-api-key)
- [Geocoding API policies](https://developers.google.com/maps/documentation/geocoding/policies)
- [Routes API policies](https://developers.google.com/maps/documentation/routes/policies)
- [Google Maps Platform pricing](https://developers.google.com/maps/billing-and-pricing/pricing)

What each Google action costs, and how the app keeps the count down, is explained for planners in
[Addresses and Google costs](addresses_and_costs.md).

## Required APIs

Enable these APIs in the Google Cloud project used by the backend:

1. Geocoding API
2. Routes API

The app does not use the legacy Distance Matrix API.

## Recommended key layout

Use separate keys for development, test/staging, and production.

For each key:

1. Enable billing on the Google Cloud project.
2. Restrict the key to the Geocoding API and Routes API only.
3. Add an application restriction:
   - production: backend server egress IP address or CIDR range;
   - development: developer workstation/public egress IP if stable;
   - if IP changes often, keep the key low-quota and rotate it after temporary use.
4. Configure low daily quotas and billing alerts while testing.
5. Store the key only in the backend environment or ignored `.env` file.

Local `.env` example:

```env
GOOGLE_MAPS_API_KEY=replace_with_backend_only_secret
GOOGLE_GEOCODING_URL=https://maps.googleapis.com/maps/api/geocode/json
GOOGLE_ROUTES_MATRIX_URL=https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix
```

## Restrict by IP address

When using IP-address application restrictions, enter the backend caller's public
egress IP address, not the browser user's address. Examples:

- `192.0.2.10`
- `192.0.2.0/24`
- `2001:db8::1`
- `2001:db8::/64`

If the backend is behind NAT, a load balancer, or a hosting platform, confirm the
platform's documented outbound IPs. If the IP changes, Google requests will fail
with a controlled provider error until the key restriction is updated.

## Live smoke test

After offline tests pass and a restricted key is available:

```powershell
& .\.venv\Scripts\python.exe scripts/live_smoke_m3.py
```

The script geocodes two public Toronto-area addresses and calculates a 2x2 driving
matrix. It prints only counts and pass/fail summaries; it does not print the key,
coordinates, or full provider responses.

## Cost controls

- Streamlit reruns do not trigger matrix calculations.
- Matrix calculation happens only after an explicit button click or API call.
- Google matrices are not cached or stored (decision D6, see below): within a session the
  app reuses its current matrix, and a new session calculates again after showing the cost.
  Matrices from the offline provider are still cached by provider, ordered locations,
  travel mode, routing preference, and departure bucket.
- Default Routes API batching limits are capped by environment settings:
  `ROUTES_MAX_ORIGINS`, `ROUTES_MAX_DESTINATIONS`, and `ROUTES_MAX_ELEMENTS`.
- The app default maximum route-matrix element count is 625, matching the
  documented Compute Route Matrix cap for a request.
- `POST /api/v1/matrices/estimate` reports billable elements, the number of Google
  requests, and whether the cache already holds the matrix, without calling Google.
  Above `MATRIX_CONFIRM_ELEMENTS` (default 400) it reports that confirmation is needed.

### Address resolution (Version 1.1)

- `POST /api/v1/locations/resolve` sends each distinct address once: duplicates
  (ignoring case and extra spaces) share one Geocoding request.
- Requests carry the region bias `GEOCODE_REGION_CODE` (default `ca`); a request may
  override it.
- Found results are cached for `GEOCODE_CACHE_TTL_SECONDS`, which cannot be set above
  30 days. The cache row stores the parsed matches and timestamps only: no address
  text, no key, no raw Google response. Not-found answers are not cached, and expired
  rows are deleted when the backend starts.
- A cache hit keeps the original `geocoded_at`, so the 30-day limit counts from the
  moment Google answered, not from the latest cache read.
- `GET /api/v1/config` tells the UI whether a key is configured, without revealing it.

### Logging

httpx logs every request URL at INFO level, and Geocoding URLs carry the key and the
raw address in the query string. Since V1.1-M1 the backend limits the `httpx` and
`httpcore` loggers to warnings (in `configure_logging` and whenever the Google adapter
is created), so neither appears in the log at any `LOG_LEVEL`. Version 1.0 did write
both to the log at the default `INFO` level: if a Version 1.0 backend ran with a real key,
treat its old log files as containing the key, delete them, and consider rotating the key.

## Google usage terms that shape Version 1.1

Re-read on 2026-11-16 for milestone V1.1-M0, and again on 2026-11-22 for the Version 1.1
release (V1.1-M7). This section records how the app is designed around the terms; it is
not legal advice. Re-check the live pages before each release, because wording and section
numbers change.

What the 2026-11-22 reading found, compared with M0:

- Both policy pages now state the 30-day coordinate exception directly, listing the Routes
  API and the Geocoding API among the services that grant it. Place IDs may still be kept
  indefinitely.
- "Distance matrix results" are still listed among content not to store outside the
  Services, and no exception covers distances or durations, so decision D6 stands.
- Attribution now asks for "Google Maps" rather than "Google", which is what the app
  shows. Google prefers its logo, and for text attribution it also gives typography rules
  (font, size 12 to 16 sp, colour, never wrapped or translated). The app shows the words in
  its caption style; check them against the current rules before a production deployment.

Sources:

- [Geocoding API policies](https://developers.google.com/maps/documentation/geocoding/policies) — read directly.
- [Routes API policies](https://developers.google.com/maps/documentation/routes/policies) — read directly.
- [Google Maps Platform Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)
  — the binding text. Automated fetching returned no content on 2026-11-16, so the clauses
  below marked *(terms, via search)* come from search-engine excerpts of this page and must
  be confirmed by reading it in a browser.
- [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms) — Google
  Maps Content may be cached only as the Service Specific Terms expressly permit.

| Rule | Status | How Version 1.1 complies |
|---|---|---|
| Geocoding latitude/longitude may be cached for at most 30 consecutive calendar days, then deleted. | Policy page, read directly | Decision D2: geocode cache and stored coordinates carry `geocoded_at`; anything older than 30 days is not used and is re-resolved (plan §8.6). Since V1.1-M1 the cache TTL cannot exceed 30 days, expired rows are purged at start-up, and validation warns `GEOCODE_EXPIRED`. |
| Place IDs may be stored indefinitely. | Policy page, read directly | Place IDs are kept with each location. |
| Geocoding API content must not be used in conjunction with a non-Google map. | *(terms, via search)* | Decision D1: Google-derived locations are shown only through Google — an "Open route in Google Maps" link per truck, and an embedded Google map only if a separate browser-restricted embed key is configured. The Folium/OpenStreetMap map remains only for scenarios whose coordinates were supplied in JSON (such as the samples). |
| Routes API latitude/longitude may be cached for at most 30 days. | Policy page, read directly (2026-11-22) | Same 30-day ceiling as geocodes. |
| Routes API distances and durations: no express permission to cache was found; the policy page lists "distance matrix results" among content not to bulk-download or store outside the Services. | Policy page read directly; terms not readable | **Decision D6, option (a), settled 2026-11-18** (plan §4). Since V1.1-M3, Google matrices are stored nowhere:<br>• not in the matrix cache;<br>• not in saved scenarios (the backend drops an embedded Google matrix and says so);<br>• not in the app's JSON downloads.<br>At backend start, Google matrices that Version 1.0 cached or saved are removed. Matrices from fixtures or the offline provider are unaffected. Within a session the app reuses its current matrix and recalculates only on an explicit click. |
| Content shown in the app needs Google Maps attribution unless it is on a Google map that already shows it. | Policy pages, read directly | Since V1.1-M6, "Matched addresses: Google Maps" and "Travel times: Google Maps" appear on the Scenario, Locations, Travel times, and Results pages, and in exports, wherever that content comes from Google. |

Google's support pages state they cannot give legal advice; consult legal counsel before a
production deployment.

## Failure handling

Since V1.1-M7 a rejection's message ends with "Google says: …", Google's own reason taken
from its error body. The key is removed from it (as sent, URL-encoded, or anything shaped
like a Google key), it is cut to one line of at most 300 characters, and it is shown to the
planner but never written to the log. A departure time in the past is refused before any
request is sent, because Google rejects it for driving.

Common recovery actions (more in [troubleshooting](troubleshooting.md#google-errors)):

- `GOOGLE_API_KEY_MISSING`: set `GOOGLE_MAPS_API_KEY` in backend environment.
- invalid key or IP restriction: verify the key value, API restrictions, and
  backend egress IP.
- quota/rate-limit error: wait for quota reset or increase quota after billing
  approval.
- partial/unreachable route response: fix unreachable locations or use a known
  complete matrix; the backend fails closed rather than returning a corrupt plan.

Never paste a real API key into support notes. Provide the request ID, API error
code, approximate time, and environment name instead.
