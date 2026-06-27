# Google Maps Platform setup and restrictions

This app uses Google Maps Platform only from the backend. Do not place Google API
keys in Streamlit code, frontend session state, uploaded files, sample data,
exports, or build logs.

Official references checked for the Version 1 release:

- [Google Maps Platform security guidance](https://developers.google.com/maps/api-security-best-practices)
- [Routes API overview](https://developers.google.com/maps/documentation/routes)
- [Compute Route Matrix overview](https://developers.google.com/maps/documentation/routes/compute-route-matrix-over)
- [Compute Route Matrix request guide](https://developers.google.com/maps/documentation/routes/compute_route_matrix)
- [Geocoding API overview](https://developers.google.com/maps/documentation/geocoding/guides-v3/overview)
- [Geocoding API setup](https://developers.google.com/maps/documentation/geocoding/guides-v3/get-api-key)

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
- The backend caches route matrices using provider, ordered locations, travel
  mode, routing preference, and departure bucket.
- Default Routes API batching limits are capped by environment settings:
  `ROUTES_MAX_ORIGINS`, `ROUTES_MAX_DESTINATIONS`, and `ROUTES_MAX_ELEMENTS`.
- The app default maximum route-matrix element count is 625, matching the
  documented Compute Route Matrix cap for a request.

## Failure handling

Common recovery actions:

- `GOOGLE_API_KEY_MISSING`: set `GOOGLE_MAPS_API_KEY` in backend environment.
- invalid key or IP restriction: verify the key value, API restrictions, and
  backend egress IP.
- quota/rate-limit error: wait for quota reset or increase quota after billing
  approval.
- partial/unreachable route response: fix unreachable locations or use a known
  complete matrix; the backend fails closed rather than returning a corrupt plan.

Never paste a real API key into support notes. Provide the request ID, API error
code, approximate time, and environment name instead.
