# Exception Resolution Playbook (v3.1)

## Section 0: Ground Rules

Always check the customer's account tier before deciding on a resolution. VIP and
Premium customers have different SLA commitments than Standard customers.
Document everything: log the reason for every decision in the shipment notes.
Aim to choose a resolution path within 30 minutes of the exception being flagged.
When in doubt, err on the side of the customer: a small gesture now (a proactive
call, a service credit) prevents a bigger problem later.

## Section 1: Failed Delivery Attempts

First attempt: routine. Schedule a redelivery for the next business day. No
customer contact required for Standard tier beyond a notification that we tried
and when we'll be back. For Premium and VIP customers, always send a notification.

Second attempt: be proactive. Send the customer a notification with options:
confirm they'll be home for a third attempt, or reroute the package to a nearby
locker (see Section 6). For VIP customers, also offer a specific delivery time
window if available. Check the customer's exception history: if they've had more
than 3 exceptions in the last 90 days, flag to the shift supervisor even though
it's only the second attempt.

Third attempt: this is the escalation threshold. Do not schedule a fourth attempt
without supervisor approval. The standard path is to hold the package at the depot
for 5 business days and notify the customer with pickup instructions, or reroute
to a locker if eligible. For VIP customers, escalate to the supervisor
immediately. If the package is perishable, do not hold at the depot; see Section 5.

Driver notes matter. If the driver mentions a security gate, a broken buzzer, or a
dog, that should influence whether we reattempt or reroute. If a gate code doesn't
work, contact the customer for an updated code before rescheduling.

## Section 2: Address Mismatches

Building or street not found: hold the shipment at the depot and contact the
customer to verify. Send a notification asking them to confirm or update the
address. Give them 48 hours to respond; if no response, initiate return-to-sender.
For VIP customers extend to 72 hours and have the supervisor attempt a phone call
before returning.

Missing apartment or unit number: do not leave the package in the lobby or with a
doorman unless the customer explicitly authorized it. Hold the shipment, contact
the customer for the unit number, then schedule redelivery for the next business
day. Fragile or perishable packages get higher urgency.

Clearly invalid address (vacant lot, demolished building): may indicate a
fraudulent order. Hold the package, do not reattempt, and escalate to the fraud
review team. Document the driver's observations.

## Section 3: Damaged Packages

Minor cosmetic damage (small dent, torn label, light scuffing): proceed with
delivery, note the damage, tell the customer to inspect contents.

Moderate damage (crushed corner, box partially open, audible shifting of
contents): do not deliver. Pull the package and notify the customer with two
options: deliver as-is if they accept the risk, or initiate a replacement.

Severe damage (package leaking, contents visible, strong odor): do not deliver
under any circumstances. Initiate an immediate replacement order with the shipper
and notify the customer with an apology and updated timeline.

Fragile items: lower the threshold by one level. What would be minor damage for a
standard package is treated as moderate for a fragile one. Err on the side of
pulling the package.

VIP customers: any damaged package triggers a proactive apology notification.
Include a service credit of $5 for minor damage, $10 for moderate damage. For
severe damage the supervisor personally handles the communication.

## Section 4: Refused Deliveries

Accept the refusal; never argue. Log the refusal reason. Initiate return-to-sender
(package ships back to origin within 2 business days). Send the customer a
confirmation that the refusal is processed and the item is being returned.

If the customer says they didn't order it: verify the address matches the
shipment record. A mismatch is an address issue (Section 2). If the address
matches, proceed with the return and flag the order for customer service review.

Premium and VIP refusals: shift supervisor reviews the case within 24 hours.
Repeated refusals may indicate a systemic upstream issue.

## Section 5: Weather Delays

Standard packages: send a notification with an honest updated delivery window.
SLA timers pause during declared weather events; the only failure is failing to
communicate.

Perishable packages, critical rule: if the estimated delay exceeds 4 hours, do
not attempt delivery. The item is likely compromised. Pull it from the route
immediately and initiate a replacement with the shipper. Notify the customer with
an apology and, for Premium and VIP customers, a service credit. If the delay is
under 4 hours, use judgment; frozen goods are more forgiving than fresh produce.
If unsure, treat as over 4 hours and pull it.

Fragile packages: weather does not change handling requirements, but inspect at
the depot after extended transit through a storm.

## Section 6: Locker Reroute Procedures

Eligibility, all must hold:
1. Package size must fit the locker's max_package_size (a LARGE package cannot go
   to a SMALL or MEDIUM locker).
2. Locker must have capacity. FULL: never reroute there. LIMITED: only SMALL
   packages.
3. Locker must be in the same zip code as the delivery address or an adjacent zip.
4. Perishable packages are never rerouted to lockers (no temperature control);
   prefer redelivery or replacement.

Customer notification for a locker reroute must include: the locker address, its
operating hours, the pickup deadline (3 business days, then returned to depot),
and a note that they can request home redelivery instead (about 2 extra business
days).

When not to reroute: a VIP's first failed attempt deserves a redelivery offer
with a time window instead. A fragile package already in transit for days gains
handling risk from an extra move.

## Section 7: Escalation Matrix

Automatic escalation triggers, escalate to shift supervisor immediately:
- Third failed delivery attempt on any shipment, regardless of tier
- Any exception involving a VIP customer with 3 or more exceptions in the last 90 days
- Any damaged perishable package (including weather-compromised perishables)
- Address issues suggesting possible fraud (vacant lot, demolished building)
- Any situation where the driver reports a safety concern

Discretionary escalation:
- Premium customer with a perishable package delayed more than 2 hours
- Standard customer with more than 5 exceptions in 90 days (systemic pattern)
- Anything that doesn't fit the playbook; flag rather than miss

When escalating, provide: shipment ID, summary of the exception and actions so
far, the customer's tier and exception history, and a recommended next step.

## Section 8: Customer Communication Guidelines

Channel: VIP and Premium customers get EMAIL. Standard customers get SMS, kept
brief and actionable.

Tone: FORMAL customers get structured, polite language in full sentences. CASUAL
customers get a friendlier conversational tone. Never be flippant.

Every exception notification must include:
1. What happened, in plain language, not a status code
2. What we're doing about it, the specific resolution
3. What happens next, the timeline and any action needed from the customer
4. An apology proportional to severity

Service credits: if the customer has an active credit on their account, reference
it when relevant; acknowledge that this is not their first issue and that extra
steps are being taken.
