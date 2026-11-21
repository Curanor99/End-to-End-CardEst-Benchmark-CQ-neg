"""Shared base selection, coverage balancing, and CQ rendering."""

from collections import Counter
from pathlib import Path
import re


SOURCE = Path(__file__).resolve().parents[1] / "stats_CEB" / "stats_CEB.sql"
ALIAS = re.compile(r"(\w+)\s+as\s+(\w+)", re.IGNORECASE)
REFERENCE = re.compile(r"\b(\w+)\.(\w+)\b")
EQUALITY = re.compile(r"\s*(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)\s*")



def parse(line):
    _, query = line.split("||", 1)
    if not query.endswith(";"):
        raise ValueError(f"Missing semicolon: {query}")
    head, where = query[:-1].split(" WHERE ", 1)
    if not head.startswith("SELECT COUNT(*) FROM "):
        raise ValueError(f"Unexpected query: {query}")
    sources = []
    for source in head[len("SELECT COUNT(*) FROM "):].split(", "):
        match = ALIAS.fullmatch(source)
        if not match:
            raise ValueError(f"Unexpected relation: {source}")
        sources.append((match.group(1), match.group(2)))
    aliases = {alias for _, alias in sources}
    conditions = []
    for text in re.split(r"\s+AND\s+", where):
        refs = {alias for alias, _ in REFERENCE.findall(text)}
        if not refs or not refs <= aliases or len(refs) > 2:
            raise ValueError(f"Unexpected condition: {text}")
        if len(refs) == 2 and not EQUALITY.fullmatch(text):
            raise ValueError(f"Unexpected join: {text}")
        conditions.append((text, refs))
    return query, sources, conditions


def select_bases(lines):
    """Keep every source query and its 1-based line number."""
    return [(number, *parse(line)) for number, line in enumerate(lines, 1)]


def prefix_exposures(tables):
    return Counter((depth, table) for depth in range(1, len(tables) + 1)
                   for table in tables[:depth])


def balanced_sequences(candidates_by_base, table_for, template_for=None):
    """Reduce coverage skew by swapping whole sequences for one base at a time."""
    groups = []
    for base, candidates in candidates_by_base.items():
        group = []
        for order in candidates:
            tables = tuple(table_for(base, atom).lower() for atom in order)
            templates = (Counter((position, template_for(atom))
                                 for position, atom in enumerate(order, 1))
                         if template_for is not None else Counter())
            group.append((order, prefix_exposures(tables), templates))
        groups.append((base, group))

    tables, templates = Counter(), Counter()
    chosen = {}
    for base, group in groups:
        chosen[base] = group[0]
        tables.update(group[0][1])
        templates.update(group[0][2])

    def added_cost(counts, exposures):
        # Change in sum of squared counts when adding a candidate to the other bases.
        return sum(n * (2 * counts[key] + n) for key, n in exposures.items())

    def score(candidate):
        return added_cost(tables, candidate[1]), added_cost(templates, candidate[2])

    changed = True
    while changed:
        changed = False
        for base, group in groups:
            current = chosen[base]
            tables.subtract(current[1])
            templates.subtract(current[2])
            best = min(group, key=score)
            if score(best) < score(current):
                chosen[base] = best
                changed = True
            tables.update(chosen[base][1])
            templates.update(chosen[base][2])
    return {base: choice[0] for base, choice in chosen.items()}


def print_table_coverage(orders, table_for):
    counts = Counter()
    for base, order in orders.items():
        counts.update(prefix_exposures(tuple(table_for(base, atom).lower() for atom in order)))
    print("Negated atom counts by emitted query depth (physical tables):")
    for depth in sorted({depth for depth, _ in counts}):
        print(f"  {depth}: " + ", ".join(
            f"{table}={count}" for (level, table), count in sorted(counts.items())
            if level == depth
        ))


def split_conditions(conditions, negative):
    outer = []
    inner = {alias: [] for alias in negative}
    for text, refs in conditions:
        involved = refs & negative
        if len(involved) > 1:
            raise ValueError(f"Join between negated relations: {text}")
        (inner[next(iter(involved))] if involved else outer).append(text)
    return outer, inner


def equality_keys(alias, terms):
    pairs = []
    for term in terms:
        match = EQUALITY.fullmatch(term)
        if not match:
            continue
        a, ac, b, bc = match.groups()
        if a == alias and b != alias:
            pairs.append((f"{b}.{bc}", f"{a}.{ac}"))
        elif b == alias and a != alias:
            pairs.append((f"{a}.{ac}", f"{b}.{bc}"))
    if not pairs:
        raise ValueError(f"Negated relation {alias} has no positive join")
    return pairs
