# Addresses and Google costs

The app uses two Google Maps Platform services, both called only by the backend and only when you press a button:

- **Geocoding** turns each address into a place on the map. The **Resolve addresses** button on the Locations page uses it.
- **Routes** (Compute Route Matrix) gives the driving time and distance between every pair of locations. The **Calculate travel times** button on the Travel times page uses it.

Everything else is free: checking the scenario, solving, changing settings, exports, and saving. Setting up the Google key is described in [Google API setup](google_api_setup.md).

Google bills per request or per element, with prices and monthly free amounts that change from time to time. Check the current [Google Maps Platform pricing](https://developers.google.com/maps/billing-and-pricing/pricing) and set a budget alert on the Google Cloud project.

## Resolving addresses

### What is sent

- Only addresses that are new or have changed since they were last resolved. The button says how many: **Resolve addresses (N pending)**.
- Each distinct address once. Two locations with the same address (ignoring case and extra spaces) share one request.
- Addresses resolved in the last 30 days are answered from the backend's cache, at no cost.
- Each request carries a region bias, `GEOCODE_REGION_CODE` (default `ca`, Canada), so an ambiguous address prefers a match in that country.

One address costs at most one Geocoding request. Resolving the same scenario again costs nothing until an address changes or 30 days pass.

### Statuses

| Status | Meaning | What to do |
|---|---|---|
| **Resolved** | Google found one precise match. | Nothing. |
| **Needs review** | Google found a match, but it may be the wrong place. The reason is shown. | Compare your address with the matched one, then **Confirm match**, pick another match with **Use this address**, or **Correct the address**. |
| **Not found** | Google found nothing. | Correct the address, then **Retry not found**. |
| **Not resolved yet** | New, or imported. | **Resolve addresses**. |
| **Address changed — resolve again** | The address was edited after it was resolved. | **Resolve addresses**. |
| **Older than 30 days — resolve again** | The match expired (see the 30-day rule below). | **Resolve addresses**. |
| **Supplied coordinates** | The coordinates came with the JSON (as in the samples), not from Google. They are trusted as in Version 1.0. | Nothing. |

A location is ready for travel times when it is Resolved (directly or after you confirm it) or has supplied coordinates.

### Reasons for a review

| Reason | What Google returned | Typical cause |
|---|---|---|
| Partial match | Only part of the address matched. | A misspelt street, a unit number Google does not know, or a wrong postal code. |
| Low precision | A town, postal area, or street rather than a building. | The address has no street number, or Google knows only the area. |
| Several matches | More than one place fits. | A street name that exists in several towns. Pick the right one. |
| Far from the plant | The match is more than `GEOCODE_MAX_PLANT_DISTANCE_KM` (default 500 km) in a straight line from the plant. | The right street in the wrong city or country. |

When two locations resolve to the same place, the result says so. This is only a note; check that it is intended.

The far-from-plant check has a limit: at the default 500 km, the wrong city in the same region can pass. For example, a Mississauga address matched in Ottawa (about 370 km away) is accepted. The matched address is always shown beside the one you typed, so check it. A fleet that works within one region should set `GEOCODE_MAX_PLANT_DISTANCE_KM` lower, for example 150.

### Hard-to-find addresses

- Add the town and postal code.
- Use the company's name with the town, for example "Acme Steel, Vaughan, ON".
- For a site without a street address, such as a yard or a gate, use a [Plus Code](https://maps.google.com/pluscodes/).
- If Google offers several matches, pick the right one rather than confirming the first.

### The 30-day rule

Google allows the app to keep matched coordinates for at most 30 days. After that:

- The location shows "Older than 30 days — resolve again" and must be resolved before new travel times.
- Its address, Google's place ID, and your confirmation are kept, so resolving it is one click and a previously confirmed match is not asked about again.
- Saved scenarios and kept unsaved edits lose expired coordinates when they are opened, and at every backend start. The app says how many need resolving again.

Coordinates supplied in JSON are not affected.

## Calculating travel times

### What is counted

For *n* locations (the plant included), a travel-time calculation is an *n* × *n* matrix:

- **Elements:** *n* × *n*, one for each ordered pair of locations. Google bills per element.
- **Requests:** Google takes at most 25 origins and 25 destinations (625 elements) per request, so larger matrices are split into several requests. With traffic-aware optimal routing the limit is 100 elements per request.

| Locations | Elements | Requests (without traffic) |
|---|---|---|
| 10 | 100 | 1 |
| 20 | 400 | 1 |
| 25 | 625 | 1 |
| 50 | 2,500 | 4 |
| 100 | 10,000 | 16 |

Before anything is sent, the Travel times page shows the locations, billable elements, and requests. Above 400 elements (`MATRIX_CONFIRM_ELEMENTS`) you tick a confirmation first.

The traffic-aware options under **Advanced: routing options and recalculation** are billed at a higher rate than the default "without traffic".

### Travel times are not stored

Google's terms give no permission to store distances and durations, so the app does not (decision D6):

- Travel times from Google last for your session. They are left out of saved scenarios, kept unsaved edits, and JSON downloads.
- After the backend restarts, or when a saved scenario is opened again, they are calculated again, with the cost shown first.
- Within a session they are reused until something they depend on changes, and never recalculated without a click.

Travel times that came with the JSON, as in the samples, are stored and reused as in Version 1.0.

### What makes travel times stale

| Change | Travel times | Google call |
|---|---|---|
| Add a location, or change an address | Stale: calculate again | Yes, when you press **Calculate travel times** |
| Change the routing options | Stale: calculate again | Yes, when you press it |
| Delete a location | Still current: the matrix is trimmed | No |
| Change trucks, shifts, tasks, the buffer, or the objective | Still current | No |

### Keeping costs down

- Delete locations that no task or shift uses; the Travel times page names them. Every location adds a row and a column.
- Resolve and calculate once the location list is complete, not after every addition.
- Leave **Recalculate travel times** alone unless Google's road network has changed in a way that matters.
- Plan a large scenario in one session rather than reopening it several times, because each new session calculates the travel times again.

## Limits

- **Locations:** up to 100 per travel-time calculation (10,000 elements).
- **Addresses:** up to `API_MAX_GEOCODE_ADDRESSES` (default 100) per **Resolve addresses** press.

Scenario-size guidance for solving is in [troubleshooting](troubleshooting.md#scenario-size).
