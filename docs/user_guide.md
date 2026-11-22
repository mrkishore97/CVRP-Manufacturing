# User guide

This guide walks through the app page by page, in the order a plan is built. To install and start the app, see the [README](../README.md). Two companion guides go deeper:

- [Addresses and Google costs](addresses_and_costs.md): how addresses are matched, and what each Google action costs.
- [Objectives and priorities](objectives_and_priorities.md): how the Optimize settings and task priorities shape a plan.

## The sidebar

The sidebar lists the pages in working order:

- **Build:** Scenario, Locations, Fleet, Tasks.
- **Plan:** Review, Travel times, Optimize, Results.
- **Advanced:** JSON.

Below the pages, **Status** shows where the open scenario stands:

- **Backend:** connected or unavailable. "Google Maps configured" means the backend has a key; the key itself is never shown.
- **Scenario:** its ID and name, and whether it has unsaved edits. "Kept if the page reloads" means a browser refresh will not lose them.
- **Inputs:** ✅ Valid (with any warnings), ❌ errors, or ⏳ not checked yet. The app checks the scenario automatically after every change; checking is free.
- **Locations:** how many are ready for travel times, and how many need attention.
- **Travel times:** ✅ current, ⚠️ stale (something they depend on changed), or ⬜ none.
- **Plan:** ✅ current, ⚠️ stale and hidden (the inputs changed since it was made), or ⬜ none.

Free work happens on its own. Anything Google charges for, resolving addresses and calculating travel times, happens only when you press its button.

## Scenario

A scenario is one planning problem: a plant, the places trucks visit, the trucks and their shifts, and the PO tasks for a planning period.

- **Open, save, or start over**
  - **Open sample:** pick from the **Sample** list: the feasible sample (a complete scenario with travel times, opened at start), the deadline issue and fleet shortage samples (to see how problems are reported), and the address-only sample (to try address resolution).
  - **Open saved scenario:** pick from the list of saved scenarios. Each shows how many plans it has.
  - **Start a new empty scenario.**
  - **Save scenario** stores the scenario under its ID. If another saved scenario already has that ID, the app asks first: **Replace saved …** or **Keep the saved one**.
  - **Save as a new scenario** saves a copy under a new name and ID and continues in the copy. It never overwrites.
  - **Duplicate or delete the chosen saved scenario:** Duplicate copies a saved scenario without opening it. Delete needs the tick **Yes, delete it permanently** and removes the scenario with its plans and its kept unsaved edits.
- **Details:** the scenario name, the plant timezone, and the planning period. The scenario ID follows the name until you set one under **Advanced: scenario ID**.
- **Plant:** the plant's name and address. The plant is the first location and the default start and end of every shift. **Advanced: use another location as the plant** makes an existing location the plant.
- **Defaults for new tasks:** pickup and delivery service minutes, and the unit label for quantities (pallets, kg, skids…).

The planning period grows by itself when you add a shift or task outside it, and the app says so. It never shrinks by itself.

## Locations

A location needs only a **name** and an **address**. Nobody types coordinates.

1. **Add a location** with its name and address. Company names, postal codes, and Plus Codes also work for sites that are hard to find.
2. Press **Resolve addresses (N pending)**. Only new or changed addresses are sent to Google.
3. Each location gets a status:
   - **Resolved:** ready for travel times.
   - **Needs review:** Google's match is doubtful. The row shows your address beside the matched one and the reason. **Confirm match** if it is right, or **Correct the address** and resolve again. Where Google offers other matches, **Use this address** picks one.
   - **Not found:** correct the address, then **Retry not found**.

The reasons for a review, and what resolving costs, are in [Addresses and Google costs](addresses_and_costs.md).

Other actions:

- **Edit, duplicate, or delete** a location. Changing an address clears its match, so it is resolved again. Deleting a location that tasks or shifts use asks whether to delete those too. The plant cannot be deleted.
- **Import locations from a spreadsheet:** a CSV or Excel file with name and address columns. Download the template first. A row updates the location with the same ID, or the only one with the same name; other rows are added.
- **Copy locations from a saved scenario:** addresses already present are skipped.

Matched coordinates are kept for at most 30 days, as Google's terms require. After that the location needs resolving again; the address and your confirmation are kept, so it is one click.

## Fleet

**Trucks**

- **Add truck:** a name, a capacity in the scenario's unit, and optionally tags (comma-separated, for example `refrigerated`), a maximum route time (h:mm), and a maximum route distance (km). Both limits are enforced by the solver and checked again in every plan.
- A disabled truck stays in the scenario but is never planned.
- **Duplicate truck** and **Delete truck** are in the truck's edit form. Deleting a truck asks whether to delete its shifts too.

**Shifts**

A truck works only during its shifts. Each shift has a day, a start and end time, and where it starts and ends (the plant unless you choose another place).

- **Add shift** adds one. An end time at or before the start time ends on the next day, so a night shift such as 22:00–06:00 is one shift.
- **Copy to the next day** duplicates a shift one day later.
- **Generate shifts** (the first tab) creates many at once: choose trucks, a first and last day, the weekdays, and the hours, then **Preview shifts**. Shifts that already exist or overlap another shift of that truck are flagged and skipped; the rest are added together.

A shift cannot be longer than 24 hours through the form. A longer shift can be entered in Advanced JSON.

## Tasks

Each task is one PO to move.

1. Choose the **movement**:
   - **Pickup (supplier → plant):** the plant end is filled in.
   - **Drop (plant → customer):** the plant end is filled in.
   - **Pickup-drop (A → B):** two places other than the plant.
2. Fill in the PO number, the places, the quantity, the ready time (goods available from), and the due time.
3. **Deadline applies to:** *Delivery complete* (delivered and unloaded by the due time, the default) or *Pickup complete* (loaded by the due time; delivery may follow later in the shift).
4. **Priority** from 1 Routine to 5 Critical. It matters only when not everything fits; see [Objectives and priorities](objectives_and_priorities.md).
5. Optionally, required truck tags, service minutes, and notes.

The app warns at once when no enabled truck has the required tags, or none that has them can carry the quantity.

- The table filters by movement, location, and priority.
- **Duplicate task** copies the lane, times, and load with a new ID; replace the PO number marked "(copy)".
- **Import from a spreadsheet** (a tab of its own): download the task template, fill it in, upload it, and check the preview. Locations may be given by ID or by exact name, and the plant end of a pickup or drop may be left empty. Choose **Append as new tasks**, **Update tasks with matching IDs, add the rest**, or **Replace all tasks**. Any row error blocks the import, so a file is applied completely or not at all.

## Review

Review lists every issue in the scenario, grouped by section: Scenario, Locations, Trucks, Shifts, Tasks, and Travel times.

- **Errors** stop solving. **Warnings** do not, but explain things the solver cannot fix, such as a task whose time window overlaps no shift of a suitable truck, a truck without shifts, or a location nothing uses.
- **Go to** opens the row that needs fixing.
- **Fit the planning period to shifts and tasks** appears when something lies outside the period.
- **Task times** shows each task's times in plant time and in UTC.

## Travel times

The solver needs the driving time and distance between every pair of locations.

- The page shows whether every location is ready. Unresolved ones are listed, with **Resolve them on the Locations page**.
- Before anything is sent, it shows what the calculation costs: the number of locations, the billable elements (one per pair of locations), and the number of Google requests.
- Above 400 billable elements (about twenty locations) you tick a confirmation first.
- **Calculate travel times** sends the request. It is the only billable action on this page.
- Locations that no task or shift uses are named, because every location adds to the cost.

Google travel times are not stored, as Google's terms require (decision D6). They last for your session. After the app is restarted, or a saved scenario is opened again, they are calculated again, with the cost shown first. Travel times that came with the JSON, as in the samples, are stored as before.

**Advanced: routing options and recalculation**

- **Driving times:** without traffic (the default), or traffic-aware options that Google bills at a higher rate.
- **Departure time:** used by the traffic-aware options. It must be in the future.
- **Recalculate travel times** recalculates even when they are current. It needs its own tick and is rarely needed.

## Optimize

Choose how the plan is made, then press **Solve route plan**.

- **Objective:** Fewest trucks (the default, as in Version 1.0), Least travel, or Balanced workload.
- **Search effort:** Standard returns as soon as it has a good plan. Thorough keeps improving until the time limit.
- **Time limit (seconds):** up to the server's maximum.
- **Travel-time buffer (%):** plans every leg slower than Google's car times, to allow for trucks.
- **Advanced:** the cost of an extra truck in kilometres (Fewest trucks only) and the balance strength (Balanced workload only).

No setting relaxes a rule: capacity, deadlines, shifts, truck tags, and route limits always hold. Changing a setting needs no new travel times. Each solve is stored as a new plan.

The settings are explained in [Objectives and priorities](objectives_and_priorities.md).

## Results

- **Overview:** one sentence says how the solve went: every PO planned, some left out, or none possible. Then the figures: truck-shifts used of those available, POs planned, total distance and driving time, the longest route, and the tightest slack before a deadline. "Made with" names the settings.
- **Not planned (N):** POs left out, highest priority first, each with the reason and a suggested action. Problems with the whole solve, such as running out of time, are shown apart.
- **Trucks:** one row per truck-shift used, with its times, distance, and peak load against capacity.
- **Routes:** each route's stops in order, with location names, PO numbers, quantities, and plant-local times. A time after midnight says "(+1 day)".
  - **Open in Google Maps** opens the route with its stops in order. Google allows nine stops between start and end in a link, so a longer route gets several links, each starting where the last ended. Phones may show fewer stops per link.
- **Route map:** shown only for scenarios whose coordinates came with the JSON, such as the samples. Google's terms do not allow addresses matched by Google to be drawn on another map, so those routes use the Google Maps links.
- **Exports**
  - **Download run sheets (XLSX):** one printable sheet per truck-shift for the driver, with local times, names, addresses as typed, POs, and quantities.
  - **Download plan workbook XLSX:** every table, plus the settings the plan was made with.
  - **Download route stops CSV** and **Download diagnostics CSV.**
- **Compare plans:** every stored plan of this scenario, newest first, side by side. "Inputs: Same" means a plan was made from the same locations, fleet, shifts, tasks, and travel times, so any difference comes from the settings. **View this plan** opens an earlier plan, clearly dated; **Back to the current plan** returns.

Where addresses or travel times come from Google, the page says "Google Maps", as Google's terms require.

## Advanced JSON

The JSON page shows the same scenario the forms edit. Use it for integrations, bulk edits, and troubleshooting.

- **Apply JSON** replaces the scenario with the edited text, but only if it is valid; invalid JSON never replaces the scenario.
- **Open uploaded file** loads a JSON file. Version 1.0 files load unchanged.
- **Download clean JSON** holds the planner's inputs only, safe to share. **Download complete JSON** also holds the matched coordinates and any travel times that may be stored. Google travel times are left out of both.
- Coordinates appear only in the complete download, never in the forms.

## Unsaved edits and refresh

While a scenario has unsaved edits, the app keeps a copy of them on the backend after every change. If the browser is refreshed or closed, opening the app again offers **Restore unsaved changes** or **Discard them**. Restoring brings back the edits, any stored travel times, and the plan if it was current. Google travel times are not kept, so they are calculated again.

The page address carries the scenario ID (`?scenario=…`), so a bookmark or refresh reopens the same scenario.

Two browser tabs on the same scenario share one kept copy; the later change wins.
