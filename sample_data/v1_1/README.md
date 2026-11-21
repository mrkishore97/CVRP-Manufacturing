# Version 1.1 fixtures

New fixtures for Version 1.1 live here (plan §15). The Version 1.0 fixtures in
`../canonical/` and `../v1_0_compat/` are unchanged.

| File | Fixture | Content |
|---|---|---|
| `v11_a_address_only.json` | V11-A | Address-only plant, three suppliers, three customers; three trucks with one shift each; pickup, drop, and pickup-drop tasks. No coordinates and no travel times. |
| `v11_f_priority_shortage.json` | V11-F | One truck and six full-truck drops on the same lane with priorities 1–5; only two fit before the deadline, so the partial plan keeps priorities 5 and 4. |
| `v11_g_vehicle_tags.json` | V11-G | A refrigerated truck and a standard truck; two tasks require `REFRIGERATED`. |
| `v11_h_route_limits.json` | V11-H | A truck limited to 2:30 of route time and one limited to 60 km; each task fits only one of them. |
| `v11_i_multiday_shift_depots.json` | V11-I | Three days of generated-style shifts; Truck 1 ends each day at a hub instead of the plant. |

V11-F to V11-I reuse the Version 1.0 canonical locations (with supplied coordinates) and travel times, trimmed to the locations each scenario uses, so they validate without warnings and solve offline.

## V11-A addresses

The seven addresses are public civic buildings in the Greater Toronto Area (city halls
and civic centres). They stand in for a plant, suppliers, and customers so the sample
can be resolved live with a Google key in a demo. The names say which building each
address belongs to. No business or person is implied.

Automated tests never call Google: they resolve these addresses through the offline
fake provider with configured answers.
