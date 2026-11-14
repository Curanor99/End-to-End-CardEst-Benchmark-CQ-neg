#!/usr/bin/env python3
"""Generate matching anti-join workloads from the supplied CardEst SQL file."""

from pathlib import Path
import csv
import io
import re


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent.parent / "stats_CEB" / "stats_CEB.sql"
# Keep the same base queries as the existing and added-negation workloads.
SOURCE_LINES = (
    6, 7, 8, 9, 10, 11, 17, 18, 19, 20, 21, 22, 25, 26, 27, 28, 29,
    30, 31, 40, 41, 42, 43, 44, 80, 81, 86, 89, 90, 91, 92, 93, 94,
    95, 96, 97, 117, 118, 119, 120,
)
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


def sequence(sources, conditions):
    aliases = [alias for _, alias in sources]
    edges = [refs for _, refs in conditions if len(refs) == 2]

    def connected(positive):
        reached = {next(iter(positive))}
        while True:
            expanded = reached | set().union(
                *(edge for edge in edges if edge <= positive and edge & reached)
            )
            if expanded == reached:
                return reached == positive
            reached = expanded

    def search(selected):
        best = ()
        for alias in aliases:
            if alias in selected:
                continue
            negative = selected | {alias}
            positive = set(aliases) - negative
            if not positive or any(edge <= negative for edge in edges):
                continue
            if not connected(positive):
                continue
            if not any(alias in edge and edge & positive for edge in edges):
                continue
            candidate = (alias,) + search(negative)
            if len(candidate) > len(best):
                best = candidate
        return best

    return search(set())


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


def build_sql(sources, conditions, negative, style):
    outer, inner = split_conditions(conditions, negative)
    positive = [(table, alias) for table, alias in sources if alias not in negative]
    negatives = [(table, alias) for table, alias in sources if alias in negative]
    if style == "except":
        return build_except(positive, negatives, outer, inner)
    if style == "left_join":
        from_sql = " CROSS JOIN ".join(f"{table} as {alias}" for table, alias in positive)
        for table, alias in negatives:
            from_sql += f" LEFT JOIN {table} as {alias} ON " + " AND ".join(inner[alias])
            _, matched_column = equality_keys(alias, inner[alias])[0]
            outer.append(f"{matched_column} IS NULL")
    else:
        from_sql = ", ".join(f"{table} as {alias}" for table, alias in positive)
        for table, alias in negatives:
            terms = inner[alias]
            if style == "not_exists":
                outer.append(
                    f"NOT EXISTS (SELECT 1 FROM {table} as {alias} WHERE "
                    + " AND ".join(terms) + ")"
                )
                continue
            keys = equality_keys(alias, terms)
            local = [term for term in terms
                     if {a for a, _ in REFERENCE.findall(term)} == {alias}]
            missing = " OR ".join(f"{column} IS NULL" for column, _ in keys)
            left = ", ".join(column for column, _ in keys)
            right = ", ".join(column for _, column in keys)
            if style == "not_in":
                tuple_expr = f"({left})" if len(keys) > 1 else left
                non_null = [f"{column} IS NOT NULL" for _, column in keys]
                predicate = (
                    f"{tuple_expr} NOT IN (SELECT DISTINCT {right} FROM {table} as {alias}"
                    f" WHERE " + " AND ".join(local + non_null) + ")"
                )
            else:
                raise ValueError(f"Unknown style: {style}")
            outer.append(f"({missing} OR {predicate})")
    where = " WHERE " + " AND ".join(outer) if outer else ""
    return f"SELECT COUNT(*) FROM {from_sql}{where};"


def build_except(positive, negatives, outer, inner):
    keys = {alias: equality_keys(alias, inner[alias]) for _, alias in negatives}
    from_sql = ", ".join(f"{table} as {alias}" for table, alias in positive)
    where = " WHERE " + " AND ".join(outer) if outer else ""
    predicates = []
    for table, alias in negatives:
        pairs = keys[alias]
        left = ", ".join(column for column, _ in pairs)
        right = ", ".join(column for _, column in pairs)
        local = [term for term in inner[alias]
                 if {a for a, _ in REFERENCE.findall(term)} == {alias}]
        filter_sql = " WHERE " + " AND ".join(local) if local else ""
        key_aliases = {column.split(".", 1)[0] for column, _ in pairs}
        key_sources = ", ".join(
            f"{name} as {source_alias}" for name, source_alias in positive
            if source_alias in key_aliases
        )
        key_filters = [term for term in outer
                       if {a for a, _ in REFERENCE.findall(term)} <= key_aliases]
        key_filters.extend(f"{column} IS NOT NULL" for column, _ in pairs)
        key_where = " WHERE " + " AND ".join(key_filters)
        nulls = [f"{column} IS NULL" for column, _ in pairs]
        outer_keys = left
        if len(pairs) > 1:
            outer_keys = f"({outer_keys})"
        predicates.append(
            "(" + " OR ".join(nulls) + f" OR {outer_keys} IN "
            f"(SELECT {left} FROM {key_sources}{key_where} EXCEPT "
            f"SELECT {right} FROM {table} as {alias}{filter_sql}))"
        )
    return f"SELECT COUNT(*) FROM {from_sql}{where}" + (
        " AND " if outer else " WHERE "
    ) + " AND ".join(predicates) + ";"


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


def main():
    results = {style: [] for style in ("not_exists", "not_in", "except", "left_join", "cq")}
    source_lines = SOURCE.read_text(encoding="utf-8").splitlines()
    omitted = []
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    writer.writerow(("id", "source_line", "negated_count", "positive_aliases", "negated_aliases"))
    if max(SOURCE_LINES) > len(source_lines):
        raise ValueError("Source workload does not contain all selected query lines")
    for line_number in SOURCE_LINES:
        line = source_lines[line_number - 1]
        query, sources, conditions = parse(line)
        order = sequence(sources, conditions)
        omitted.extend(f"{line_number}.{i}" for i in range(len(order) + 1, len(sources)))
        for i in range(len(order) + 1):
            negative = set(order[:i])
            identifier = f"{line_number}.{i}"
            writer.writerow((
                identifier, line_number, i,
                " ".join(alias for _, alias in sources if alias not in negative),
                " ".join(order[:i]),
            ))
            for style in results:
                if style == "cq":
                    output = build_cq(sources, conditions, negative)
                elif not negative:
                    output = query
                else:
                    output = build_sql(sources, conditions, negative, style)
                results[style].append(f"{identifier}||{output}")
    for style, lines in results.items():
        (ROOT / f"{style}.sql" if style != "cq" else ROOT / "cq.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    (ROOT / "manifest.csv").write_text(manifest.getvalue(), encoding="utf-8")
    (ROOT / "omitted_ids.txt").write_text("\n".join(omitted) + "\n", encoding="utf-8")
    print(f"Selected source queries: {len(SOURCE_LINES)}")
    print(f"Queries per file: {len(results['cq'])}")
    print(f"Omitted further sequence levels: {len(omitted)}")
    print("Omitted IDs:", ", ".join(omitted))


if __name__ == "__main__":
    main()
