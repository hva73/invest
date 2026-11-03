# ESCAPE — END-TO-END DATA CONTRACT

Contract version: **1.0.0**, 3. november 2026. Status: review on `codex/design-review-wip`; **not a release or permission to install**. Covers Trading Radar/ChatGPT → ESCAPE report/API ingestion → persistence → broker/market observations → display/readback. No automatic changes to prompts, schedules, mandates or production data.

## 1. Existing contracts and precedence

Before creating this document, the repository was checked for an equivalent contract. There was no standalone end-to-end contract. Responsibilities were distributed across REPORT_V2.md, REPORT_VALIDATION.md, MCP_REPORTS.md, MCP_DELIVERY.md, CANDIDATE_STATUS_MODEL.md, HOTWATCH_ENGINE.md, POSITION_ASSESSMENTS.md, TRADING.md and the design specification. This document connects them; it does not silently replace their schemas.

Machine truth: report_v2.SCHEMA and report_validation.transport_schema for reports; hotwatch_contract for engine requests/observations; pluto_trade_contract.json for verified broker tool inputs. DESIGN_STATUS_SPEC_V1_DA.md governs the approved presentation. Any conflict must be reported in the change-impact record, not resolved by guessing or rewriting archived reports.

## 2. Ownership, authority and responsibility

| Field/status family | Producer / owner | ESCAPE responsibility | Authority / restrictions |
|---|---|---|---|
| report_id, generated_at, source, report_type, is_test, sources | Trading Radar/ChatGPT | Validate, preserve immutable payload/category, receipt/digest/readback | Sender timestamp is not a broker or market timestamp |
| candidate_id | Trading Radar chooses stable instrument identity; ESCAPE preserves identity | Validate uniqueness, retain across omission/reports, enforce tenant/test isolation | Ticker alone is not identity; do not reuse for another instrument |
| trade_cycle_id | Trading Radar or explicitly documented ESCAPE session origin | Preserve separate cycles under the same candidate; validate references | Reopening is not a new candidate; historical cycle is not overwritten |
| candidate analysis, catalyst, sources, recommendation, reason, deadline, next_trigger, proposed buy/exit plan | Trading Radar/ChatGPT | Validate/store, show age and provenance, preserve updates as new evidence | Recommendation is an analysis, not an order or fill |
| lifecycle reported by a report | Trading Radar/ChatGPT claim; ESCAPE owns the event journal and projection | Append status event, preserve reported_status and reason; guard reactivation | POSITION_OPEN/EXIT_WATCH claims require broker evidence for actual ownership |
| actual portfolios/Collections, asset_id, quantity, cost basis, orders, fills, order status/time, available broker operations | Pluto | Read owned snapshots, maintain original time/status, reconcile without overwriting reports | Pluto is authoritative; sender execution_source=pluto is not authentication |
| market price/volume/spread, feed type, venue, event time, delay, official close | Actual EODHD/Pluto feed | Validate identity, session/currency/reference; keep sources separate | Subscription name is not proof of rights or real-time access; no invented values |
| receive time, validation/receipt result, canonical digest, local IDs and ownership | ESCAPE | Generate server-side; expose safe diagnostics/readback | Never replace event time with receive time |
| deterministic features, final engine signal, risk result, rule score, strategy version/checksum | ESCAPE HOT WATCH Engine | Store versioned inputs/decisions and separate from order execution | Signal is not a trade; display changes cannot alter active strategy |
| broker assessment link | ESCAPE, using exact owned depot reference and asset identity | Preserve both broker facts and report claims; explicit mismatch warning | No ticker/name-only matching or cross-depot copying |
| daily/since-last/FX/P&L calculations | ESCAPE only when all required source evidence exists | Retain formulas, reference times, source and currency; otherwise unknown | Raw account-value delta is not cashflow-adjusted daily return |
| active/history grouping, sorting, freshness, missing-data reasons | ESCAPE UI projection | Follow approved design policy; counts and displayed sets agree | No deletion, automatic broker status change or historical payload mutation |
| original historical report | Sender content, immutable ESCAPE archive | Complete original readback | Current active filters do not rewrite the old report |

## 3. Three independent status dimensions

- Lifecycle: DISCOVERED, ANALYZING, HOT_WATCH, WAITING_TRIGGER, BUY_SIGNAL, ORDER_PENDING, POSITION_OPEN, EXIT_WATCH, CLOSED, ARCHIVED. The ordering is not forced linear. New catalyst/reactivation requires reason and preserves history/candidate identity.
- Decision: report wire format retains KØB, AFVENT, FRAVÆLG; display normalization BUY/WAIT/REJECT does not change the stored enum or mean broker execution. Individual held-position assessments remain independent of candidate decisions.
- Broker execution: provider-authoritative PROPOSED/AWAITING_APPROVAL/SUBMITTED/ACCEPTED/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED/EXPIRED/UNKNOWN with actual quantity/time evidence. Accepted does not mean filled. Cancelled after partial fill preserves actual filled quantity; only the remainder is terminal.

Engine session state CREATED/VALIDATING/ACTIVE/PAUSED/DEGRADED/EXPIRED/COMPLETED/ERROR and engine signal BUY/WAIT/SELL/REDUCE/NO_DATA/PAUSE are additional independent domains. No display grouping may write a state transition back to the engine or broker.

FRAVÆLG cannot remove a held position. Candidate omission in the next report cannot delete a candidate or prove a sale. A report deadline cannot expire or cancel a real broker order. No terminal historical fill may close a new unrelated cycle.

## 4. Wire changes versus UI-only projections

| Change | Sender consequence | Receiver consequence | Coordinated schema change? |
|---|---|---|---|
| Spacing, typography, compact table, detail disclosure | None | UI/browser regression | No |
| Sorting and active/history filters over existing fields | None unless previously missing input becomes needed | Counts, critical exceptions and archival readback tests | No; do not reinterpret enum meaning |
| Freshness badges for quote 60s / snapshot 300s / analysis 24h | Existing valid source times remain unchanged | Central policy, market/session/calendar context, original time retained | Not for badge alone; new provenance inputs require a documented contract |
| Dashboard combines actual broker facts and optional report assessment | Sender must not treat dashboard read format as report payload | New separate read projection; preserve raw report APIs | Dashboard format is separately versioned; report format changes only if a new reference is introduced |
| Optional portfolios[].broker_reference | Sender may add exact provider/external_id when known; may omit | Strict optional schema, exact owner/type/asset match, unknown on absence | Yes, additive v2 extension; old reports remain valid |
| New data-status/reason/provenance fields in a report | Must learn exact schema before sending; no arbitrary keys | Shared validation/schema/tool export/examples/readback updated together | Yes, additive or new major version depending on requiredness/semantics |
| New lifecycle or decision enum / meaning | Prompt/client handling and tests reviewed | Validator, journal, projection, filters and read tools reviewed | Yes; not a CSS patch |
| Broker status normalization | Sender's old report claim retained; new definition documented | Provider evidence, fill quantity, terminal/uncertain handling tested | Internal derived label may be additive; wire enum changes require coordination |
| New mandatory timestamp/reference/field | Old sender may fail | Must support old version or stage migration | Breaking; new major report version or explicit capability negotiation |
| Trade flow, authorization scopes, automation, active strategy | Requires separate explicit authorization | Separate implementation and regression | Outside this design authorization |

`broker_reference` does not confer provider authority and does not make sender-supplied verification trustworthy. It is a matching hint verified against a server-owned portfolio and actual asset. Fields not present remain null/unknown, not zero or synthetic in production.

## 5. Identity, immutable events and idempotence

- Stable IDs are scoped to the authenticated ESCAPE owner and test category. Existing report_id uniqueness is per ESCAPE user across categories: changing test/production category requires a new report_id.
- Same report_id + identical canonical payload is a safe retry with duplicate=true and the same database ID. Changed content under the same ID is a conflict, never an overwrite.
- New report content uses a new report_id. Candidate IDs/cycle IDs remain stable when describing the same identity/cycle. Same ticker in separate depots has separate position identity and assessment.
- Observation/session IDs have their own documented domains; do not reuse report retry rules as an excuse to alter a prior observation. Identical retries deduplicate; altered immutable content conflicts.
- Lifecycle, decision, order-evidence and important engine events are append-only through application APIs. Correction is new evidence with reason/time/origin, not editing old events. This is application-level immutability, not a claim of tamper-proof storage against a database administrator.
- Projection sorting/hiding does not delete. Original payload and digest remain unchanged. No backfill invents prior broker fills, source timestamps, FX or market observations.

## 6. End-to-end protocol and readback

1. Sender discovers the actual versioned tool schema/capabilities and uses exact enum/required/null rules. An `args: unknown` client rendering does not authorize guessing; the concrete exported schema and validate_report are the fallback.
2. Sender builds a complete report in the authorized category with stable references and actual source times; unknown data stays null. Validate the exact object intended for sending.
3. Receiver runs the same shared validation, scoped reference checks and canonical size limits inside the save transaction. No partial report/candidate journal is committed on validation failure.
4. Sender calls send_report for the authorized report. A successful transport alone is not proof of saved content: inspect structuredContent, delivery_status, ID, duplicate and validation warnings.
5. Sender reads back the exact report, comparing report_id, content/category and critical fields. get_latest_report reads latest by the documented ordering; it must not be used as proof of a specific older ID if a newer report arrived concurrently. Exact report-item readback is used when available; otherwise mark that exact check not verified.
6. Candidate persistence is checked separately with get_hot_watch(candidate_id,is_test). MCP 2.5.1 returns candidate and lifecycle_history even with groups=[]. groups=[] only means no separate observations.
7. get_hot_watch_engine requires hotwatch:read; ordinary report readback requires reports:read. Existing scopes are never automatically expanded. No user prompt may bypass server authorization.
8. Retrying identical report content is tested; omissions in subsequent reports must not remove prior candidate history. A read result from the wrong owner/category must contain no other tenant's data.

## 7. Time, financial references and data quality

All persisted times have explicit timezone and normalize to UTC; display uses Europe/Copenhagen. Keep generated_at, source event time, provider status time, receive time, calculation time and comparison-reference time distinct.

Quote >60s at active market, snapshot >300s at open market and assessment >24h are display freshness rules. Market close/weekend/holiday exceptions require documented venue calendar/session coverage; crypto is not assumed closed on weekends. UNKNOWN market/calendar must be displayed honestly. Feed delay remains visible.

Day comparison requires actual documented official-close definition/reference; since-last requires same asset/source/feed/venue/currency/session/price/adjustment basis and increasing source times. Invalid or missing reference means neutral —. Absolute price/value/cash/quantity/cost are neutral. Financial sign and analysis-action urgency are separate.

DKK requires a broker DKK field or documented FX basis/time. Raw value differences cannot be labelled daily portfolio profit without complete cashflow correction. Missing fees/cost basis must not be disguised as a verified net result. Provider-reported P/L retains its provider label. NOT_PROVIDED/NOT_FETCHED/STALE/SOURCE_ERROR/NOT_APPLICABLE are display reasons unless explicitly added to the wire schema.

## 8. Versioning and compatibility

- This contract uses semantic versioning independently of report schema_version, MCP server version, dashboard read-model version and engine strategy version/checksum.
- Patch: clarification or compatible bug fix with unchanged field meaning. Minor: optional additive fields/capabilities with old payloads accepted. Major: new mandatory fields, incompatible meaning/enum or identity rules.
- Current report wire versions 1 and 2 remain accepted. New optional fields are defined in one schema source and exported consistently to HTTP/MCP/examples. No destructive migration or historical JSON rewrite.
- Receiver support lands and is tested before an optional sender extension is enabled. Old sender + new receiver and new sender + new receiver must pass; old receivers must reject unsupported fields clearly, without sender silently stripping meaningful data to make a report fit.
- Updating receiver code does not update a deployed Trading Radar prompt. Any sender prompt/config change is a separate reviewable task. Record schema digest/version and actual client tool exposure; refresh/reconnect clients when their cached tool definition is stale.
- Existing active engine version, strategy parameters, broker permissions, request budgets, cron/jobs and mandates are unchanged by a design deployment.

## 9. Integration acceptance at both ends

Sender-side contract tests: exact v1/v2 shape, optional-reference omission/inclusion, consistent IDs/cycles/source refs, null/zero distinction, timestamps, no future or fabricated verification, validation-before-send and immutable retry. Explicit failures must be reported instead of silently removing candidates/fields.

Receiver-side tests: atomic validation+save+journal, original payload/digest unchanged, tenant/category isolation, idempotent duplicate/conflict, candidate omission persistence, reactivation and multiple cycles, broker/report conflict, no false fill, exact readback and pagination. Test no broker-write on validation/read/display actions.

Shared end-to-end scenario: report1 contains A/B → report2 changes A on same candidate/cycle and omits B → validate/send/exact readback → candidate readback proves A's events and B's persistence → exact retry returns same ID/duplicate → incompatible retry rejects with no mutation. Keep a recorded fixture/version/expected receipt. Repeat with old sender payload and new optional broker_reference payload.

Design T01–T28 results must be listed individually with PASS/FAIL/BLOCKED/NOT_RUN, fixture/command/code version and limitations. A synthetic provider/calendar test does not establish production feed/calendar access. A pass in receiver fixtures is not proof that the separately deployed Radar prompt was tested. Real client/plugin tests require explicit readback evidence from that client and authorized test category. Existing owner test IDs must not be rewritten or re-sent with changed content.

## 10. Mandatory impact analysis before future changes

Every future change affecting report/status/time/filter/identity/reference semantics must include a reviewable record before implementation or enabling it:

1. Problem, proposed behavior and exact affected fields/statuses/time rules.
2. Owners: sender, receiver, broker, market provider, UI or multiple parties.
3. Classification: UI-only / additive wire / breaking wire / authorization or automation; concrete schema/version/digest effect.
4. Impact on Trading Radar prompt, producer payload, receiver validator, storage/migration, lifecycle journal, readback, counts/filters and archived reports.
5. Identity/idempotency/cycle consequences and behavior for missing/old/unknown inputs.
6. Financial meaning/provenance, currency/session/calendar requirements and invalid-comparison behavior.
7. Tenant/test isolation and security/mandate consequences; no inferred permission expansion.
8. Old↔new sender/receiver compatibility, end-to-end fixtures, negative cases and T01–T28 subset/full regression.
9. Rollout order, client tool refresh/capability negotiation, data-source rights, explicit unresolved blockers and safe fallback.
10. Rollback plan preserving any newly appended journal/trade evidence; release/installation authorization is separate.

No automatic prompt edit, status reclassification, automation change, acquisition or trade is authorized by writing an impact record. If a necessary capability is missing, document the exact gap and a backward-compatible solution; do not fabricate evidence to make the UI look complete.

## 11. Impact record for the current WIP

Changes so far: new read-only dashboard projection and central display policy, additive observation/cache tables and optional portfolios[].broker_reference. This optional field affects the shared wire schema and requires exported schema/examples/validator tests; existing senders can omit it. The sender prompt has not been changed. New dashboard output is not a send_report payload.

Current source gaps: verified official close/reference, complete cashflow history, documented FX/time and venue-calendar coverage. Display must remain unknown where absent. Preserve old APIs/archive and include MCP 2.5.1 readback. Full T01–T28 evidence and remaining live-source limitations are required for review. Nothing in this record authorizes release, installation or production changes.

## 12. HOT WATCH som selvstændig matematisk motor

Det normative motorafsnit er [HOTWATCH_ENGINE_DATA_CONTRACT.md](HOTWATCH_ENGINE_DATA_CONTRACT.md). Det dokumenterer eksplicit overdragelse fra Radar/MCP, felt-/statusansvar, faktiske parametre/formler, risk/exit/anti-noise, adaptergulve og budgetter, pollingophør, otte særskilte H01–H08-integrationstests samt kendte arkitekturforskelle. Motorens state og signaler er uafhængige af kandidatens lifecycle og Radarens analytiske beslutning. UI-filtre og rapportstatus må ikke styre polling. Ingen strategi-, polling-, automations- eller mandatændring er godkendt som del af redesign.

## 13. Aktuelle additive læseændringer

- dashboard read model `design-1` i /api/state er adskilt fra rapportpayloads. Brokerreference er valgfri på v2-porteføljer, med gammel afsender kompatibilitet og streng ekstranøglevalidering testet.
- /api/v1/hotwatch/sessions?view=current|history er en UI-læseprojektion. Historie kan bladres med before/limit. Den ændrer ikke engine claim/control eller kildens requestbudget. Oprindelig pagineret læsning og MCP-scopes er bevaret.
- UI opdaterer gemt motorstatus med samme 15s-interval. Flere DB-læseprojektioner er ikke nye providerpolls. Uafklarede kildefejl er adskilt fra handelsbeslutning.
- market quote output har en additiv daily_comparison-værdi, aktuelt null uden verificeret officiel reference. Rå dailyChange-data beholdes, men UI udleder ikke en dokumenteret officiel close fra dem.
- Journalen mærker manglende provider-status-tid som observeret status, ikke som et nyligt udført fill. Gammel rapport og faktisk broker-evidens står separat.

Ingen af disse ændringer opdaterer Trading Radar-prompten eller starter en motorsession automatisk.
