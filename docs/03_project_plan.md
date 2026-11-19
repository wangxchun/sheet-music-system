# 03 Project Plan

| Item | Details |
|---|---|
| Client | ○○ Piano Studio |
| Document version | v1.0 |
| Date | 20/03/2026 |

## 1. Timeline

| Phase | Work | Timing | Acceptance criteria |
|---|---|---|---|
| 0 | Requirements interviews and baseline measurement | Week 1 | Client confirms priorities and acceptance criteria; pre-rollout timing done |
| 1 | Pilot: 20 books | Week 2 | Effort estimate done; all four teachers try it and confirm the columns and workflow |
| 2 | Full cataloguing | Weeks 3–8 | 80% of frequently used materials catalogued; 0 data-check errors |
| 3 | Level and style tags | Weeks 6–10 (overlaps phase 2) | Every catalogued piece has a level |
| 4 | Demonstration recordings | Weeks 9–12 | The 30 most-taught pieces have recordings |
| 5 | Handover and training | Week 12 | Owner can add a book independently; acceptance report signed |
| Follow-up | Usage check | Week 4 after delivery | All four teachers are using it; improvement suggestions collected |

The timing from phase 2 onwards is adjusted based on pilot measurements and confirmed with the client before any change.

## 2. Work by phase

### Phase 0: Requirements interviews and baseline measurement

Interview questions:
- How do you usually find a piece? What kind of piece is hardest to find?
- Where are the materials kept? How many cabinets are there? Is there any existing classification?
- What devices do the teachers use: phones, tablets or computers?
- How should levels be defined? Should they map to an exam system?
- What is the budget? Is a monthly subscription acceptable?
- Who will use the recordings? What do students play them on at home?

**Baseline measurement:** ask the teachers to list 10 pieces they teach often, and time how long it takes to find each one. Record the results in `07_acceptance_report.md`. This baseline is what proves the improvement; without it, all you can say is that it "feels faster".

### Phase 1: Pilot

1. Import the catalogue template and set up sharing, the search sheet and filter views.
2. Choose 20 representative books: thick and thin, with and without contents pages, Chinese and foreign-language.
3. Catalogue them following `05_cataloguing_workflow.md`, recording the time each book takes.
4. All four teachers grade the pilot pieces together to agree on a level standard.
5. Teachers try searching on their phones; collect feedback and adjust the columns.
6. Estimate the total effort from the measurements and confirm the scope with the client.

**The purpose is to reduce risk:** fixing a format problem at 20 books costs far less than at 1,000.

### Phase 2: Full cataloguing

- Work in batches by cabinet, labelling spines after each batch.
- Run the data-check tool at the end of every batch and fix errors on the spot.
- Do frequently used materials first. Rarely used books can be catalogued at book level only, with pieces added later.

### Phase 3: Level and style tags

- Each teacher tags the pieces they know best.
- Resolve disagreements using the standard agreed during the pilot; the owner decides if needed.

### Phase 4: Demonstration recordings

- Teachers list the 30 pieces they teach most.
- Look for existing recordings first (option A); teachers record the rest (option B).
- If slow playback or separate hands are needed, pilot option C on 5 pieces before scaling up.

### Phase 5: Handover and training

- One training session (about 1 hour): searching, filtering, adding books and pieces, labelling.
- The owner adds a book hands-on to confirm they can do it independently.
- Complete `07_acceptance_report.md`, signed by both parties.

## 3. Effort estimate

```text
Total cataloguing hours ≈ pilot average minutes per book × books to catalogue ÷ 60
```

| Item | Value |
|---|---|
| Pilot average minutes per book | ____ minutes (filled in after the pilot) |
| Books to catalogue | ____ books |
| Estimated total effort | ____ hours |

## 4. Deliverables

| Deliverable | Location |
|---|---|
| Google Sheets catalogue (with sample rows, dropdowns, lookup columns) | Template: `system/piano_catalog.xlsx` |
| Shelf location labels | Applied on site |
| Requirements analysis, system design, project plan | `docs/01`–`03` |
| Admin manual | `docs/04_admin_manual.md` |
| Cataloguing workflow | `docs/05_cataloguing_workflow.md` |
| Teacher guide | `docs/06_teacher_guide.md` |
| Acceptance report | `docs/07_acceptance_report.md` |
| API and credentials setup | `docs/08_api_and_credentials.md` |
| Cataloguing and check tools (with tests) | `tools/`, `tests/` |

## 5. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Cataloguing takes longer than estimated | Schedule slips | Measure during the pilot; do frequently used materials first and catalogue rare books at book level only |
| Teachers don't use it | Project fails | Involve teachers from the pilot; keep the interface simple; keep only the columns they actually use |
| Inconsistent level standards | Unreliable filter results | Agree a standard during the pilot; use fixed options |
| Physical location doesn't match the catalogue | Found in the catalogue but not on the shelf | Label spines; return books by their codes |
| AI extraction errors | Wrong data | Review every row; run the data-check tool |
| Generated recordings contain wrong notes | Students practise mistakes | Supplementary use only; a teacher checks each one |
| Cloud service plans change | Higher cost or fewer features | Monthly CSV backups allow moving to another tool at any time |
