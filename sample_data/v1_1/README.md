# Version 1.1 fixtures

New fixtures for Version 1.1 live here (plan §15). The Version 1.0 fixtures in
`../canonical/` and `../v1_0_compat/` are unchanged.

| File | Fixture | Content |
|---|---|---|
| `v11_a_address_only.json` | V11-A | Address-only plant, three suppliers, three customers; three trucks with one shift each; pickup, drop, and pickup-drop tasks. No coordinates and no travel times. |

## V11-A addresses

The seven addresses are public civic buildings in the Greater Toronto Area (city halls
and civic centres). They stand in for a plant, suppliers, and customers so the sample
can be resolved live with a Google key in a demo. The names say which building each
address belongs to. No business or person is implied.

Automated tests never call Google: they resolve these addresses through the offline
fake provider with configured answers.
