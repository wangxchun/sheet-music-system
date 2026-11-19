"""Hand-written list of real public-domain piano repertoire for the demo catalogue.

Piece titles and composers are real (all composers died before 1950). What is
NOT real: which pieces share a book, the page numbers, the shelf locations,
the studio levels and the technique tags. generate.py synthesises those.

Levels are the studio's own 1-8 scale and are rough teaching estimates, not an
authoritative grading. A book's `levels=(lo, hi)` spreads levels across its
pieces in printed order (progressive collections); a piece's own `level`
overrides that.

A level belongs to the piece, not to the book: every copy of a piece has the
same level. Pieces reprinted in the graded compilations carry an explicit level
in their original book (LEVEL_OVERRIDES) that matches the compilation.
generate.py refuses to run if two copies disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from agent.vocab import BookType, Period, Style


@dataclass(frozen=True)
class PieceSpec:
    title: str
    composer: str
    level: Optional[int] = None
    style: Optional[Style] = None          # overrides the book default
    technique: Optional[str] = None        # overrides the random technique tags


@dataclass(frozen=True)
class BookSpec:
    title: str
    book_type: BookType
    period: Optional[Period]
    style: Style
    pieces: Sequence[PieceSpec]
    series: str = ""
    levels: Optional[Tuple[int, int]] = None   # None + no per-piece level = not graded yet
    pdf: bool = False                          # PDF in Drive instead of a shelf location
    notes: str = ""


def numbered(template: str, composer: str, count: int) -> List[PieceSpec]:
    return [PieceSpec(template.format(n=n), composer) for n in range(1, count + 1)]


def titled(composer: str, titles: Sequence[str]) -> List[PieceSpec]:
    return [PieceSpec(t, composer) for t in titles]


BURGMULLER = [
    ("La Candeur", "legato melody"), ("Arabesque", "staccato, fast passages"),
    ("Pastorale", "grace notes"), ("Petite Réunion", "staccato thirds"),
    ("Innocence", "ornaments, legato"), ("Progrès", "scales"),
    ("Le Courant Limpide", "rippling right hand"), ("La Gracieuse", "turns, ornaments"),
    ("La Chasse", "repeated notes, fast tempo"), ("Tendre Fleur", "chord phrasing"),
    ("La Bergeronnette", "fast triplets"), ("L'Adieu", "left-hand melody"),
    ("Consolation", "cantabile melody"), ("La Styrienne", "waltz rhythm"),
    ("Ballade", "staccato chords"), ("Douce Plainte", "expressive melody"),
    ("Babillarde", "fast passages"), ("Inquiétude", "broken chords"),
    ("Ave Maria", "chord voicing"), ("Tarentelle", "fast tempo, staccato"),
    ("L'Harmonie des Anges", "arpeggios"), ("Barcarolle", "left-hand accompaniment"),
    ("Le Retour", "repeated notes"), ("L'Hirondelle", "hand crossing"),
    ("La Chevaleresque", "dotted rhythm, staccato"),
]

SCHUMANN_68 = [
    "Melody", "Soldiers' March", "Humming Song", "Chorale", "A Little Piece",
    "Poor Orphan Child", "Hunting Song", "The Wild Horseman", "Folk Song",
    "The Happy Farmer", "Sicilienne", "Knecht Ruprecht", "May, Sweet May",
    "Little Study", "Spring Song", "First Loss", "Little Morning Wanderer",
    "The Reaper's Song",
]

TCHAIKOVSKY_39 = [
    "Morning Prayer", "Winter Morning", "Playing Hobby-Horses", "Mama",
    "March of the Wooden Soldiers", "The Sick Doll", "The Doll's Funeral", "Waltz",
    "The New Doll", "Mazurka", "Russian Song", "The Peasant Plays the Accordion",
    "Kamarinskaya", "Polka", "Italian Song", "Old French Song", "German Song",
    "Neapolitan Song", "Nanny's Tale", "Baba Yaga", "Sweet Dream", "Song of the Lark",
    "The Organ Grinder Sings", "In Church",
]
TCHAIKOVSKY_DANCES = {"Waltz", "Mazurka", "Polka", "Kamarinskaya"}

# Curated levels for pieces that the graded compilations reprint. The automatic
# spread would put, for example, BWV 939 (an easy prelude) at level 5.
LEVEL_OVERRIDES = {
    "Arabesque (Op. 100 No. 2)": 3,
    "The Happy Farmer (Op. 68 No. 10)": 3,
    "Little Prelude in C major, BWV 939": 3,
}

INVENTION_KEYS = [
    "C major", "C minor", "D major", "D minor", "E-flat major", "E major", "E minor",
    "F major", "F minor", "G major", "G minor", "A major", "A minor", "B-flat major", "B minor",
]

LITTLE_PRELUDES = [
    ("C major", 924), ("D major", 925), ("D minor", 926), ("F major", 927), ("F major", 928),
    ("G minor", 929), ("G minor", 930), ("C major", 933), ("C minor", 934), ("D minor", 935),
    ("D major", 936), ("E major", 937), ("E minor", 938), ("C major", 939), ("D minor", 940),
    ("E minor", 941), ("A minor", 942), ("C minor", 999),
]


def _graded(titles: Sequence[Tuple[str, str, int]]) -> List[PieceSpec]:
    return [PieceSpec(t, c, level=lv) for t, c, lv in titles]


BOOKS: List[BookSpec] = [
    # --- Cabinet A: method books and studies --------------------------------
    BookSpec(
        "鋼琴入門教本 第一冊", "method", None, "character_piece", series="Studio edition", levels=(1, 1),
        pieces=[
            PieceSpec("Hot Cross Buns", "Traditional", technique="five-finger position"),
            PieceSpec("Lightly Row", "Traditional", technique="five-finger position"),
            PieceSpec("Au clair de la lune", "Traditional", technique="legato, counting"),
            PieceSpec("Twinkle, Twinkle, Little Star", "Traditional", technique="hand position"),
            PieceSpec("London Bridge", "Traditional", technique="counting"),
            PieceSpec("Ode to Joy (arr.)", "Beethoven", technique="legato, hand position"),
            PieceSpec("Jingle Bells (arr.)", "Pierpont", style="pop_arrangement", technique="simple chords"),
            PieceSpec("Minuet in G (simplified)", "Petzold", level=2, style="dance", technique="phrasing"),
        ],
    ),
    BookSpec(
        "徹爾尼 599 鋼琴初步教本", "etudes", "romantic", "etude", series="Op. 599", levels=(1, 3),
        pieces=numbered("Exercise No. {n} (Op. 599)", "Czerny", 30),
    ),
    BookSpec(
        "哈農 鋼琴練指法", "etudes", "romantic", "etude", series="The Virtuoso Pianist", levels=(2, 4), pdf=True,
        pieces=[PieceSpec(f"Exercise No. {n} (Hanon)", "Hanon", technique="finger independence")
                for n in range(1, 21)],
    ),
    BookSpec(
        "布爾格繆勒 25 首練習曲 Op. 100", "etudes", "romantic", "etude", series="Op. 100", levels=(2, 4),
        pieces=[PieceSpec(f"{t} (Op. 100 No. {i})", "Burgmüller", technique=tech,
                          level=LEVEL_OVERRIDES.get(f"{t} (Op. 100 No. {i})"))
                for i, (t, tech) in enumerate(BURGMULLER, start=1)],
    ),
    BookSpec(
        "Czerny: The School of Velocity, Op. 299", "etudes", "romantic", "etude", series="Op. 299", levels=(5, 7),
        pieces=numbered("Study No. {n} (Op. 299)", "Czerny", 20),
    ),
    # --- Cabinet B: collections ---------------------------------------------
    BookSpec(
        "安娜·瑪德蓮娜·巴赫曲集", "collection", "baroque", "dance", levels=(1, 3),
        pieces=[
            PieceSpec("Minuet in F major, BWV Anh. 113", "J.S. Bach"),
            PieceSpec("Minuet in G major, BWV Anh. 114", "Petzold", level=2),
            PieceSpec("Minuet in G minor, BWV Anh. 115", "Petzold"),
            PieceSpec("Minuet in G major, BWV Anh. 116", "J.S. Bach"),
            PieceSpec("Polonaise in G minor, BWV Anh. 119", "J.S. Bach"),
            PieceSpec("March in D major, BWV Anh. 122", "C.P.E. Bach", style="character_piece"),
            PieceSpec("Musette in D major, BWV Anh. 126", "J.S. Bach", level=2),
            PieceSpec("Minuet in D minor, BWV Anh. 132", "J.S. Bach"),
        ],
    ),
    BookSpec(
        "Bach: Little Preludes", "collection", "baroque", "character_piece", levels=(3, 5),
        pieces=[PieceSpec(f"Little Prelude in {k}, BWV {n}", "J.S. Bach",
                          level=LEVEL_OVERRIDES.get(f"Little Prelude in {k}, BWV {n}"))
                for k, n in LITTLE_PRELUDES],
    ),
    BookSpec(
        "Bach: Two-Part Inventions", "collection", "baroque", "etude", levels=(5, 6),
        pieces=[PieceSpec(f"Invention No. {i} in {k}, BWV {771 + i}", "J.S. Bach",
                          technique="two-voice counterpoint, hand independence")
                for i, k in enumerate(INVENTION_KEYS, start=1)],
    ),
    BookSpec(
        "Sonatina Album", "collection", "classical", "sonata", series="Public-domain edition", levels=(3, 5),
        pieces=[
            *[PieceSpec(f"Sonatina in {k}, Op. 36 No. {i}", "Clementi")
              for i, k in enumerate(["C major", "G major", "C major", "F major", "G major", "D major"], start=1)],
            *[PieceSpec(f"Sonatina in {k}, Op. 55 No. {i}", "Kuhlau")
              for i, k in enumerate(["C major", "G major", "C major", "F major", "D major", "C major"], start=1)],
            PieceSpec("Sonatina in G major, Anh. 5 No. 1", "Beethoven", level=3),
            PieceSpec("Sonatina in F major, Anh. 5 No. 2", "Beethoven", level=4),
        ],
    ),
    BookSpec(
        "Schumann: Album for the Young, Op. 68", "collection", "romantic", "character_piece", levels=(2, 5),
        pieces=[PieceSpec(f"{t} (Op. 68 No. {i})", "Schumann", level=LEVEL_OVERRIDES.get(f"{t} (Op. 68 No. {i})"))
                for i, t in enumerate(SCHUMANN_68, start=1)],
    ),
    BookSpec(
        "Tchaikovsky: Album for the Young, Op. 39", "collection", "romantic", "character_piece", levels=(3, 5),
        pieces=[PieceSpec(f"{t} (Op. 39 No. {i})", "Tchaikovsky",
                          style="dance" if t in TCHAIKOVSKY_DANCES else None)
                for i, t in enumerate(TCHAIKOVSKY_39, start=1)],
    ),
    BookSpec(
        "Mozart: Easy Pieces and Sonatas", "collection", "classical", "sonata",
        pieces=[
            PieceSpec("Minuet in G major, K. 1", "Mozart", level=2, style="dance"),
            PieceSpec("Minuet in F major, K. 2", "Mozart", level=2, style="dance"),
            PieceSpec("Allegro in B-flat major, K. 3", "Mozart", level=2, style="character_piece"),
            PieceSpec("Minuet in F major, K. 5", "Mozart", level=2, style="dance"),
            PieceSpec("Twelve Variations on 'Ah vous dirai-je, Maman', K. 265", "Mozart", level=5,
                      style="variations"),
            PieceSpec("Sonata in C major, K. 545", "Mozart", level=5, technique="Alberti bass, scales"),
            PieceSpec("Fantasia in D minor, K. 397", "Mozart", level=6, style="character_piece"),
            PieceSpec("Sonata in A major, K. 331", "Mozart", level=7, technique="ornaments, octaves"),
        ],
    ),
    BookSpec(
        "Beethoven: Selected Piano Works", "collection", "classical", "sonata",
        pieces=[
            PieceSpec("Ecossaise in G major, WoO 23", "Beethoven", level=3, style="dance"),
            PieceSpec("Six Variations on 'Nel cor più non mi sento', WoO 70", "Beethoven", level=4,
                      style="variations"),
            PieceSpec("Für Elise, WoO 59", "Beethoven", level=4, style="character_piece",
                      technique="broken chords, pedalling"),
            PieceSpec("Sonata in G major, Op. 49 No. 2", "Beethoven", level=4),
            PieceSpec("Sonata in G minor, Op. 49 No. 1", "Beethoven", level=5),
            PieceSpec("Sonata in C-sharp minor 'Moonlight', Op. 27 No. 2", "Beethoven", level=7,
                      technique="pedalling, voicing"),
            PieceSpec("Sonata in C minor 'Pathétique', Op. 13", "Beethoven", level=7),
        ],
    ),
    BookSpec(
        "Chopin: Waltzes", "collection", "romantic", "dance",
        pieces=[
            PieceSpec("Waltz in A minor, B. 150", "Chopin", level=4),
            PieceSpec("Waltz in E minor, B. 56", "Chopin", level=6),
            PieceSpec("Waltz in B minor, Op. 69 No. 2", "Chopin", level=5),
            PieceSpec("Waltz in A-flat major 'L'adieu', Op. 69 No. 1", "Chopin", level=6),
            PieceSpec("Waltz in C-sharp minor, Op. 64 No. 2", "Chopin", level=6),
            PieceSpec("Waltz in D-flat major 'Minute', Op. 64 No. 1", "Chopin", level=7),
            PieceSpec("Waltz in G-flat major, Op. 70 No. 1", "Chopin", level=7),
        ],
    ),
    BookSpec(
        "Chopin: Nocturnes", "collection", "romantic", "character_piece",
        pieces=[
            PieceSpec("Nocturne in C-sharp minor, B. 49", "Chopin", level=6),
            PieceSpec("Nocturne in E minor, Op. 72 No. 1", "Chopin", level=6),
            PieceSpec("Nocturne in E-flat major, Op. 9 No. 2", "Chopin", level=6,
                      technique="cantabile melody, ornaments, rubato"),
            PieceSpec("Nocturne in B-flat minor, Op. 9 No. 1", "Chopin", level=7),
            PieceSpec("Nocturne in B major, Op. 9 No. 3", "Chopin", level=7),
            PieceSpec("Nocturne in C-sharp minor, Op. 27 No. 1", "Chopin", level=8),
            PieceSpec("Nocturne in D-flat major, Op. 27 No. 2", "Chopin", level=8),
            PieceSpec("Nocturne in C minor, Op. 48 No. 1", "Chopin", level=8),
        ],
    ),
    BookSpec(
        "Chopin: Preludes, Op. 28 (selection)", "collection", "romantic", "character_piece",
        pieces=[
            PieceSpec("Prelude in A major, Op. 28 No. 7", "Chopin", level=3),
            PieceSpec("Prelude in E minor, Op. 28 No. 4", "Chopin", level=4,
                      technique="left-hand chords, voicing"),
            PieceSpec("Prelude in B minor, Op. 28 No. 6", "Chopin", level=4, technique="left-hand melody"),
            PieceSpec("Prelude in C minor, Op. 28 No. 20", "Chopin", level=4, technique="chords, dynamic control"),
            PieceSpec("Prelude in D-flat major 'Raindrop', Op. 28 No. 15", "Chopin", level=6,
                      technique="repeated notes, pedalling"),
        ],
    ),
    BookSpec(
        "Mendelssohn: Songs without Words (selection)", "collection", "romantic", "character_piece", levels=(5, 7),
        pieces=[
            PieceSpec("Sweet Remembrance, Op. 19 No. 1", "Mendelssohn"),
            PieceSpec("Venetian Boat Song No. 1, Op. 19 No. 6", "Mendelssohn"),
            PieceSpec("Venetian Boat Song No. 2, Op. 30 No. 6", "Mendelssohn"),
            PieceSpec("Spring Song, Op. 62 No. 6", "Mendelssohn"),
            PieceSpec("Spinning Song, Op. 67 No. 4", "Mendelssohn", technique="fast repeated notes, staccato"),
        ],
    ),
    BookSpec(
        "Schubert: Impromptus and Moments Musicaux", "collection", "romantic", "character_piece",
        pieces=[
            PieceSpec("Moment Musical in F minor, D. 780 No. 3", "Schubert", level=4),
            PieceSpec("Impromptu in A-flat major, Op. 90 No. 4", "Schubert", level=6),
            PieceSpec("Impromptu in C minor, Op. 90 No. 1", "Schubert", level=6),
            PieceSpec("Impromptu in G-flat major, Op. 90 No. 3", "Schubert", level=7),
            PieceSpec("Impromptu in E-flat major, Op. 90 No. 2", "Schubert", level=7),
        ],
    ),
    BookSpec(
        # Deliberately not graded yet: tests "level not assigned" handling.
        "Grieg: Lyric Pieces, Op. 12", "collection", "romantic", "character_piece",
        notes="封面破損",
        pieces=[PieceSpec(f"{t} (Op. 12 No. {i})", "Grieg") for i, t in enumerate(
            ["Arietta", "Waltz", "Watchman's Song", "Elves' Dance", "Folk Melody",
             "Norwegian Melody", "Album Leaf", "National Song"], start=1)],
    ),
    BookSpec(
        "Debussy: Children's Corner", "collection", "modern", "character_piece",
        pieces=[
            PieceSpec("The Little Shepherd", "Debussy", level=4),
            PieceSpec("Jimbo's Lullaby", "Debussy", level=5),
            PieceSpec("Serenade for the Doll", "Debussy", level=6),
            PieceSpec("The Snow Is Dancing", "Debussy", level=6),
            PieceSpec("Golliwogg's Cakewalk", "Debussy", level=6, technique="syncopation, staccato"),
            PieceSpec("Doctor Gradus ad Parnassum", "Debussy", level=7, technique="fast passages, evenness"),
        ],
    ),
    BookSpec(
        "Debussy: Selected Piano Works", "collection", "modern", "character_piece", pdf=True,
        pieces=[
            PieceSpec("Rêverie", "Debussy", level=5),
            PieceSpec("The Girl with the Flaxen Hair (Préludes, Book I)", "Debussy", level=5),
            PieceSpec("Arabesque No. 1", "Debussy", level=6, technique="triplets against duplets"),
            PieceSpec("Arabesque No. 2", "Debussy", level=6),
            PieceSpec("Clair de lune (Suite bergamasque)", "Debussy", level=7, technique="pedalling, voicing"),
        ],
    ),
    BookSpec(
        "Satie: Gymnopédies and Gnossiennes", "collection", "modern", "character_piece", pdf=True,
        pieces=[
            *[PieceSpec(f"Gymnopédie No. {n}", "Satie", level=3) for n in (1, 2, 3)],
            *[PieceSpec(f"Gnossienne No. {n}", "Satie", level=4) for n in (1, 2, 3)],
        ],
    ),
    # --- Cabinet C: duets, single sheets and graded compilations -------------
    BookSpec(
        "Diabelli: Melodious Exercises, Op. 149 (four hands)", "collection", "classical", "duet", levels=(1, 2),
        pieces=numbered("Melodious Exercise No. {n} (Op. 149)", "Diabelli", 6),
    ),
    BookSpec(
        "Brahms: Hungarian Dances (four hands)", "collection", "romantic", "duet", levels=(6, 6),
        pieces=titled("Brahms", ["Hungarian Dance No. 1 in G minor", "Hungarian Dance No. 5 in F-sharp minor"]),
    ),
    BookSpec("Für Elise (single sheet)", "single", "classical", "character_piece",
             pieces=[PieceSpec("Für Elise, WoO 59", "Beethoven", level=4)]),
    BookSpec("Clair de lune (single sheet)", "single", "modern", "character_piece",
             pieces=[PieceSpec("Clair de lune (Suite bergamasque)", "Debussy", level=7)]),
    BookSpec("Maple Leaf Rag (single sheet)", "single", "modern", "dance",
             pieces=[PieceSpec("Maple Leaf Rag", "Joplin", level=6, technique="syncopation, left-hand leaps")]),
    BookSpec("The Entertainer (single sheet)", "single", "modern", "dance",
             pieces=[PieceSpec("The Entertainer", "Joplin", level=5, technique="syncopation, left-hand leaps")]),
    # Graded compilations repeat pieces from other books: "where is X?" can
    # have more than one correct answer, as in a real studio. generate.py copies
    # period/style/technique from the piece's first appearance so copies agree.
    BookSpec(
        "檢定曲集 1–2 級", "exam", None, "character_piece", series="Studio compilation",
        pieces=_graded([
            ("Minuet in G major, BWV Anh. 114", "Petzold", 2), ("Musette in D major, BWV Anh. 126", "J.S. Bach", 2),
            ("Minuet in F major, K. 2", "Mozart", 2), ("Melodious Exercise No. 1 (Op. 149)", "Diabelli", 1),
            ("Melody (Op. 68 No. 1)", "Schumann", 2), ("La Candeur (Op. 100 No. 1)", "Burgmüller", 2),
            ("Ode to Joy (arr.)", "Beethoven", 1),
        ]),
    ),
    BookSpec(
        "檢定曲集 3–4 級", "exam", None, "character_piece", series="Studio compilation",
        pieces=_graded([
            ("Little Prelude in C major, BWV 939", "J.S. Bach", 3), ("Sonatina in C major, Op. 36 No. 1", "Clementi", 3),
            ("Für Elise, WoO 59", "Beethoven", 4), ("The Happy Farmer (Op. 68 No. 10)", "Schumann", 3),
            ("Arabesque (Op. 100 No. 2)", "Burgmüller", 3), ("The Sick Doll (Op. 39 No. 6)", "Tchaikovsky", 3),
            ("Gymnopédie No. 1", "Satie", 3), ("Prelude in E minor, Op. 28 No. 4", "Chopin", 4),
        ]),
    ),
    BookSpec(
        "檢定曲集 5–6 級", "exam", None, "character_piece", series="Studio compilation",
        pieces=_graded([
            ("Invention No. 1 in C major, BWV 772", "J.S. Bach", 5), ("Sonata in C major, K. 545", "Mozart", 5),
            ("Waltz in B minor, Op. 69 No. 2", "Chopin", 5), ("Spring Song, Op. 62 No. 6", "Mendelssohn", 6),
            ("Nocturne in E-flat major, Op. 9 No. 2", "Chopin", 6), ("Arabesque No. 1", "Debussy", 6),
            ("Impromptu in A-flat major, Op. 90 No. 4", "Schubert", 6), ("The Entertainer", "Joplin", 5),
        ]),
    ),
]
