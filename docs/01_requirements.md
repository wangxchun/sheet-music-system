# 01 Requirements Analysis

| Item | Details |
|---|---|
| Client | ○○ Piano Studio |
| Document version | v1.0 |
| Date | 13/03/2026 |

## 1. Conclusion

The studio's top priority is being able to find pieces. This is a **cataloguing problem**. An off-the-shelf cloud spreadsheet plus numbered physical shelves solves it, without custom software or music-score recognition. The project is delivered in phases, in this order: finding pieces, choosing pieces by level, then demonstration recordings.

## 2. Current situation

- Four teachers (the owner plus three teachers) share the teaching materials.
- There are about 300 materials, mostly on paper, with a few PDFs.
- There is no index at the level of individual pieces. To find a piece, a teacher has to remember which book it is in and then search the shelves, which takes several minutes each time.

## 3. Requirements breakdown

| ID | Client request | Underlying problem | Type of solution | Priority |
|---|---|---|---|---|
| R1 | Can't find where a piece is | Which book and page a piece is on, and which shelf the book is on | Cataloguing and search | 1 |
| R2 | Organise materials and build a teaching database | The R1 catalogue, plus a maintenance process for new materials | Data management | 1 |
| R3 | Choose pieces by level, style and exam grade | The catalogue plus filterable tags | Classification (teachers' judgement) | 2 |
| R4 | Demonstration recordings for students to practise with at home | A playable demonstration for each piece | Content sourcing | 3 |

**Key design decision: the smallest unit in the catalogue is the piece, not the book.** Teachers look for pieces, and a single collection usually contains 20–50 of them. If only book titles were recorded, teachers would still have to leaf through books one by one.

## 4. Users and scenarios

| User | Scenario | What they need |
|---|---|---|
| Teacher | Finding a piece before or during a lesson | Type a title or composer on a phone and see the book, page and shelf within seconds |
| Teacher | Choosing a student's next piece | Filter by level, period and style |
| Owner | Buying new materials | Add them without help from a technical person |
| Students and parents | Practising at home | Get a link to a demonstration recording |

## 5. Constraints

| ID | Constraint | Impact on the design |
|---|---|---|
| C1 | Users are not technical | Use a familiar interface that works on phones |
| C2 | No engineer will maintain the system after the project | Rely on off-the-shelf cloud services; custom code is only for one-off cataloguing support |
| C3 | Limited budget | Prefer free or low-subscription options |
| C4 | Shared by four teachers | Support simultaneous searching and editing by several people |
| C5 | Materials are mostly on paper | Cataloguing is the main workload, so the cataloguing process must be efficient |
| C6 | Copyright | The catalogue records only bibliographic details and page numbers, not score content; sharing recordings and scores must comply with copyright law |

## 6. Scope

**In scope**
- A cloud catalogue (two levels: books and pieces) searchable from a phone
- Shelf location codes and labels
- Cataloguing of frequently used materials, and a process for cataloguing new ones
- Level, period and style tags
- Links to demonstration recordings for frequently taught pieces
- User guides, an admin manual and training

**Out of scope**
- Custom-built apps or websites
- Digitising score content (converting whole books into editable digital scores)
- Student management, scheduling, billing and similar features

## 7. Acceptance criteria

| Metric | How it is measured | Target |
|---|---|---|
| Time to find a piece | Time the same set of 10 commonly used pieces before and after rollout | Under 30 seconds on average |
| Cataloguing coverage | Books catalogued ÷ total commonly used materials | 80% in the first phase |
| Data quality | Number of errors reported by the data-check tool | 0 |
| Actual use | Interview the four teachers one month after delivery | All four teachers are using it |

The last metric matters most. However complete the tool is, the project has not succeeded if the teachers do not use it.
