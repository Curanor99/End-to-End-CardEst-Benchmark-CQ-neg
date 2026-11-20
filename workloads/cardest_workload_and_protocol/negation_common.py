"""Shared base selection, coverage balancing, and CQ rendering."""

from collections import Counter, defaultdict, deque
from pathlib import Path
import re


SOURCE = Path(__file__).resolve().parents[1] / "stats_CEB" / "stats_CEB.sql"
ALIAS = re.compile(r"(\w+)\s+as\s+(\w+)", re.IGNORECASE)
REFERENCE = re.compile(r"\b(\w+)\.(\w+)\b")
EQUALITY = re.compile(r"\s*(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)\s*")

ADDED_COUNT = 4
BASE_QUOTAS = ((2, 1), (3, 19), (4, 20))
TEMPLATES = (
    ("scored_comments", "comments", "n_c", "n_c.PostId = p.Id", ("n_c.Score >= 1",)),
    ("upvotes", "votes", "n_v", "n_v.PostId = p.Id", ("n_v.VoteTypeId = 2",)),
    ("body_edits", "postHistory", "n_ph", "n_ph.PostId = p.Id",
     ("n_ph.PostHistoryTypeId = 5",)),
    ("linked_posts", "postLinks", "n_pl", "n_pl.PostId = p.Id", ("n_pl.LinkTypeId = 1",)),
    ("incoming_links", "postLinks", "n_pli", "n_pli.RelatedPostId = p.Id",
     ("n_pli.LinkTypeId = 1",)),
    ("owner_badges", "badges", "n_b", "n_b.UserId = p.OwnerUserId", ()),
    ("high_reputation_owner", "users", "n_u", "n_u.Id = p.OwnerUserId",
     ("n_u.Reputation >= 1000",)),
    ("owner_scored_comments", "comments", "n_cu", "n_cu.UserId = p.OwnerUserId",
     ("n_cu.Score >= 1",)),
    ("owner_upvotes", "votes", "n_vu", "n_vu.UserId = p.OwnerUserId",
     ("n_vu.VoteTypeId = 2",)),
    ("owner_body_edits", "postHistory", "n_phu", "n_phu.UserId = p.OwnerUserId",
     ("n_phu.PostHistoryTypeId = 5",)),
)


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


def eligible_templates(tables):
    return [template for template in TEMPLATES if template[1].lower() not in tables]


def select_bases(lines):
    """Choose the same post-centered base queries for both workloads."""
    groups = defaultdict(deque)
    sizes = {size for size, _ in BASE_QUOTAS}
    for number, line in enumerate(lines, 1):
        query, sources, conditions = parse(line)
        if ("posts", "p") not in sources or len(sources) not in sizes:
            continue
        tables = {table.lower() for table, _ in sources}
        if len(eligible_templates(tables)) < ADDED_COUNT:
            continue
        groups[(len(sources), tuple(sorted(tables)))].append((number, query, sources, conditions))

    selected = []
    for size, limit in BASE_QUOTAS:
        buckets = [groups[key] for key in sorted(groups) if key[0] == size]
        taken = 0
        while taken < limit:
            before = taken
            for bucket in buckets:
                if bucket:
                    selected.append(bucket.popleft())
                    taken += 1
                    if taken == limit:
                        break
            if taken == before:
                raise ValueError(f"Not enough eligible base queries of size {size}")
    return sorted(selected)


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


def build_cq(sources, conditions, negative):
    outer, inner = split_conditions(conditions, negative)
    joins = [(text, EQUALITY.fullmatch(text)) for text, refs in conditions if len(refs) == 2]
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for _, match in joins:
        a, ac, b, bc = match.groups()
        if a not in negative and b not in negative:
            x, y = (a, ac), (b, bc)
            parent[find(y)] = find(x)
    columns = {alias: [] for _, alias in sources}
    for _, match in joins:
        a, ac, b, bc = match.groups()
        for alias, column in ((a, ac), (b, bc)):
            if alias not in negative and column not in columns[alias]:
                columns[alias].append(column)
    variables = {}
    for alias in columns:
        for column in columns[alias]:
            key = find((alias, column))
            if key not in variables:
                variables[key] = f"x{len(variables) + 1}"

    views = []
    atoms = []
    for table, alias in sources:
        name = f"V_{alias}"
        if alias in negative:
            keys = equality_keys(alias, inner[alias])
            projection_columns = [column for _, column in keys]
            args = ", ".join(
                variables[find(tuple(column.split(".")))] for column, _ in keys
            )
        else:
            projection_columns = [f"{alias}.{col}" for col in columns[alias]]
            args = ", ".join(variables[find((alias, col))] for col in columns[alias])
        atoms.append(("NOT " if alias in negative else "") + f"{name}({args})")
        terms = inner[alias] if alias in negative else outer
        filters = [text for text in terms if REFERENCE.findall(text) and
                   {a for a, _ in REFERENCE.findall(text)} == {alias}]
        # SQL equality never matches NULL, including NULL on both sides.
        non_null_columns = set()
        for _, match in joins:
            a, ac, b, bc = match.groups()
            if alias in negative:
                if a == alias:
                    non_null_columns.add(ac)
                if b == alias:
                    non_null_columns.add(bc)
            elif a not in negative and b not in negative:
                if a == alias:
                    non_null_columns.add(ac)
                if b == alias:
                    non_null_columns.add(bc)
        filters += [f"{alias}.{col} IS NOT NULL" for col in sorted(non_null_columns)]
        projection = ", ".join(projection_columns)
        selection = " AND ".join(filters) if filters else "TRUE"
        views.append(f"{name} := PROJECT_BAG[{projection}](FILTER[{selection}]({table} as {alias}))")
    return "COUNT_BAG(" + " AND ".join(atoms) + ") ; " + " ; ".join(views)
