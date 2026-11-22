# Objectives and priorities

This guide explains the settings on the **Optimize** page and the **priority** of each task: what each one does, what it never does, and how to choose. The page itself is described in the [user guide](user_guide.md#optimize).

## The rules no setting relaxes

Every plan, whatever the settings, keeps these rules:

- A truck never carries more than its capacity.
- Every PO is picked up before it is delivered, by the same truck, after its ready time and by its due time.
- A truck works only within its shifts, starting and ending where the shift says.
- A task that needs a tag (such as `refrigerated`) goes only on a truck with that tag.
- A truck's maximum route time and distance, and a shift's time limit, hold.

After solving, every route is checked again against these rules by an independent validator. A plan that failed the check would never be shown.

When the rules cannot all be met, the app returns a partial plan: as many POs as fit, and a reason for each one left out. It never bends a rule to fit one more PO.

## Objective

The objective decides which of the plans that keep the rules is "best".

| Objective | What it does | Choose it when |
|---|---|---|
| **Fewest trucks** (default) | Puts the work on as few trucks as possible. Another truck is used only when it saves more than the **cost of an extra truck** (default 1,000 km of driving). This is how Version 1.0 planned. | Trucks or drivers are the scarce, costly resource. |
| **Least travel** | Drives the fewest kilometres in total, using another truck whenever that is shorter. | Fuel and distance matter most and trucks are available. |
| **Balanced workload** | Spreads the work so no driver carries a much longer day than the others, at the cost of some extra kilometres. An empty truck is never sent out. | Long days are the problem: overtime, driver hours, late returns. |

An example, from the sample `v11_e_objective_modes.json` (six POs on one day, three trucks):

| Objective | Trucks used | Distance | Longest working time |
|---|---|---|---|
| Fewest trucks | 1 | 216 km | 7.3 h |
| Least travel | 1 | 216 km | 7.3 h |
| Balanced workload (medium) | 3 | 254 km | 3.4 h |

Here one truck happens to be the shortest plan too, so Least travel matches Fewest trucks. Balanced workload uses all three trucks: 38 km more driving for a longest working day less than half as long.

### Cost of an extra truck (Fewest trucks only)

Under **Advanced**. Another truck-shift is used only when it saves more than this many kilometres. Lower it to let the plan use more trucks for shorter routes; raise it to consolidate harder. At 0 km, Fewest trucks plans the same as Least travel.

### Balance strength (Balanced workload only)

Under **Advanced**. How many extra kilometres an hour less on the longest route is worth:

| Strength | One hour less on the longest route is worth |
|---|---|
| Light | 18 km |
| Medium (default) | 36 km |
| Strong | 72 km |

"Working time" means driving plus loading and unloading. Waiting for a ready time is not counted, so a route can still span a long elapsed day when it waits.

## Search effort and time limit

| Search effort | What it does |
|---|---|
| **Standard** (default) | Stops as soon as no small change improves the plan. Usually a second or two. |
| **Thorough** | Keeps improving the plan until the time limit, so it always takes that long. It can find better plans for larger scenarios. |

The **time limit** caps each solve, up to the server's maximum (`SOLVER_MAX_TIME_LIMIT_SECONDS`, default 120 s). When not everything fits, the solver makes a second attempt for the partial plan, so the wait can be up to twice the limit.

If the overview says the solver ran out of time, raise the time limit, or split a large scenario (see the size guidance in [troubleshooting](troubleshooting.md#scenario-size)).

## Travel-time buffer

Google's driving times are for cars. A buffer of 20 % plans every leg 20 % slower, so trucks are not planned to arrive sooner than they can. The buffer applies to travel only, not to loading or waiting, and is printed on the plan and on exports. Changing it needs no new travel times and costs nothing.

## Priority

Each task has a priority: **1 Routine** (default), **2 Normal**, **3 Important**, **4 High**, or **5 Critical**.

Priority matters only when not everything fits:

- **When every PO fits,** priority changes nothing. All are planned.
- **When they do not all fit,** the partial plan leaves out the POs whose combined priority weight is least. The weights double at each level:

  | Priority | Weight |
  |---|---|
  | 1 Routine | 1 |
  | 2 Normal | 2 |
  | 3 Important | 4 |
  | 4 High | 8 |
  | 5 Critical | 16 |

  So one Critical PO outweighs up to fifteen Routine ones, and the plan drops many Routine POs before one Critical PO.
- **Priority never breaks a rule.** A Critical PO that cannot be done at all (its window is too short for the drive, no truck has its tag, it is larger than every truck) is still reported as impossible.
- **Priority is not a guarantee.** If keeping a Critical PO would need two trucks that are not there, it is left out, and the reason says so.

The sample `v11_f_priority_shortage.json` shows this: one truck, six identical full-truck drops with priorities 1 to 5, and time for two. The plan keeps the Critical and the High PO.

### Reading the reasons

Each PO left out has a reason and a suggested action on the Results page and in the diagnostics export:

- **Impossible on its own:** the PO cannot be done even with the whole fleet to itself, for example because the drive alone takes longer than its window. Fix the PO's times, place, or quantity.
- **Not enough fleet time or capacity with the others:** the PO can be done on its own, but not together with everything else. Add shifts or trucks, widen windows, or accept that lower-priority POs wait.
- **The solver ran out of time:** the search stopped at the time limit. Raise the limit or split the scenario.

## Choosing settings

1. Start with the defaults: Fewest trucks, standard search.
2. Check the Results page. If drivers' days are uneven, try Balanced workload; if trucks are plentiful and distance matters, try Least travel.
3. Use **Compare plans** on the Results page. Plans made from the same inputs say "Inputs: Same", so any difference comes from the settings alone.
4. For a large scenario or a tight one, try Thorough search with a longer time limit.
