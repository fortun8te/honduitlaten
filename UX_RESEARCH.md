# Flow review · 23 October 2026

## Decision

Make the next action and the consequences of a change obvious. Keep everyday completion quick; make occasional shared planning deliberate. This pass improves the existing Telegram flow rather than adding another interface or more reminder rules.

The audience is two walkers and up to two parents. The core job is to know who is responsible for dogs and dishes, confirm completed work, and arrange exceptions without family members reconstructing the plan from chat history. The Pi 2B and NAS routes remain lightweight.

## Research and evidence limits

| Source | Relevant guidance | Application here |
|---|---|---|
| [Telegram bot guidelines](https://core.telegram.org/bots/guidelines) | Main-flow actions suit buttons. Inline keyboards suit menus and changes to an existing message. Start needs to explain how to begin. | Keep one changing navigation panel. Give new members short instructions and the owner a visible family setup action. |
| [NN/g: progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) | Show frequent, important actions first; make secondary options discoverable when needed. | Today leads with the viewer's next responsibility, while preserving both chores and their owners. Family setup and history stay accessible without dominating every evening. |
| [NN/g: confirmation dialogs](https://www.nngroup.com/articles/confirmation-dialog/) | Routine confirmations add friction. Important reviews should explain the consequences and use action-specific buttons. | Keep Done one tap with a correction route. Improve existing planning reviews rather than add more approval screens. Use Send request, Save N days, Accept swap and Keep current plan. |
| [GOV.UK: check answers](https://design-system.service.gov.uk/patterns/check-answers/) | Let people inspect the information they are submitting and give the final button a concrete action label. | Availability review shows current and proposed assignments, including effects on later dates. Drafts remain private and unsaved. |
| [Todoist: family collaboration](https://www.todoist.com/help/articles/collaborate-with-friends-or-family-in-todoist-tzkGUy) | One assignee per task makes responsibility explicit. | A pending swap keeps the current owner. The recipient sees the proposed owner of both chores before deciding. |
| [Nipto](https://nipto.app/) | Schedules, rotation, history and points exist together in a shared-chore product. | This confirms a relevant product category, not that more game mechanics help this household. Keep the existing plain monthly count. |

These are official product capabilities and published design guidance. Applying them to this household is a design judgment. There has not been a live family usability study, so no adoption, error-rate or time-saving claim is made. Competitor marketing is not evidence of effectiveness.

## What was weak in the existing flow

- Availability review said that the plan could change, without showing who would get which chore.
- Swap wording described a general rule about dishes. The actual result depends on completion, parent coverage and the evening cutoff.
- Today showed the household list but did not first answer what this particular person needed to do next.
- A long requests inbox repeated details and decision buttons for several proposals at once.
- Generic confirmation labels made the reader infer whether the tap saved a schedule, sent a request or corrected a completion.

## Approaches considered

1. **Add more management features.** More reminder settings and score features could serve occasional needs, but they increase choices without evidence that this family needs them.
2. **Make free text the main interface.** Typing can be a useful shortcut, but relying on it makes people learn what the parser understands and remember commands.
3. **Guide the existing task flow. Chosen.** Put the immediate action first, retain shared context, and show concrete consequences where a decision affects someone else. Keep typing as an optional shortcut.

The counterargument to the chosen approach is over-confirmation. A review on every tap would slow ordinary use and train people to ignore important decisions. The design therefore keeps routine completion immediate and improves the existing review step for scheduling and corrections. It does not add another approval layer.

## Resulting journeys

### Start and Today

The first line explains the viewer's next chore/time, an outstanding confirmation, a request needing a reply, or that their own work is finished. Both household chores remain visible beneath it. Before 03:00, unfinished work from the previous evening takes priority over the new day. Parents see a distinction between assigned work, a need for cover and actual confirmed completion. A new owner can find the family invitation action immediately.

### Change availability

Choose dates → review current/proposed dogs and dishes assignments → Save N days.

The summary shows the chosen dates first and explicitly counts any additional selected or later dates affected. Optional seven-row detail pages expose the whole proposal without making every small change a long message. Completed work, parent coverage and delivered assignments are identified only where relevant. Preview and save use the same availability policy, with simulation confined to an in-memory copy. No schedule or notification changes occur before the existing confirmation. Cosmetic name/language changes do not invalidate the review; relevant scheduling changes still do.

Visual inspection exposed a real policy tradeoff: the existing rule counts covering as a turn, so a weekend change can shift later dates. This pass retains that established rule and makes its consequences visible. Silently changing the household's fairness rule would be a separate product decision. The summary states how many later dates change and why; the full list is always available before saving.

### Request a swap

Choose a date → inspect both chores and any later changes → Send request.

The recipient opens a concise inbox item, sees the concrete proposal, and chooses Accept swap or Keep current plan. Long proposals use the same short-summary/optional-detail pattern. The saved proposal stays unchanged while browsing its pages. If the dishes cutoff or another relevant change makes the effect different, the bot presents the revised tasks and requires a fresh acceptance. It never silently interprets an old acceptance as approval for a different effect.

### Finish and correct

Done remains one tap. The task card and derived point count update. A mistaken or forgotten confirmation can be corrected through personal history with the existing private review. The point total remains an account of completed work, not a separate mutable score.

## Acceptance checks

- The daily flow does not require remembering a command.
- Today keeps both tasks visible while giving the viewer a useful next step.
- Every availability preview matches the state produced by confirmation, including later rotation effects.
- Preview, cancellation and reading a request write no live scheduling records and notify no other family member.
- Acceptance after a changed effect requires another explicit decision.
- Long names, full-month changes and multiple requests fit Telegram's message and callback limits.
- Existing one-tap completion, ownership checks, corrections, points and private approval boundaries continue to pass.
- Polling, shutdown, supervision, health checks and reminder cadence are outside this UX change. Device-specific performance and actual family use remain separate validation steps.
