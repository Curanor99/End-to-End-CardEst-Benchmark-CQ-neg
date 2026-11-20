#!/usr/bin/env python3
"""Generate matching anti-join workloads from the supplied CardEst SQL file."""

from pathlib import Path
import csv
import io
import sys


ROOT = Path(__file__).resolve().parent
# Find the shared module even when invoked directly from another directory.
sys.path.insert(0, str(ROOT.parent))
import negation_common as common


def longest_sequences(sources, conditions):
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
        best = [()]
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
            for suffix in search(negative):
                candidate = (alias,) + suffix
                if len(candidate) > len(best[0]):
                    best = [candidate]
                elif len(candidate) == len(best[0]):
                    best.append(candidate)
        return best

    return search(set())


def sequence(sources, conditions):
    return longest_sequences(sources, conditions)[0]


def build_sql(sources, conditions, negative, style):
    outer, inner = common.split_conditions(conditions, negative)
    positive = [(table, alias) for table, alias in sources if alias not in negative]
    negatives = [(table, alias) for table, alias in sources if alias in negative]
    if style == "except":
        return build_except(positive, negatives, outer, inner)
    if style == "left_join":
        from_sql = " CROSS JOIN ".join(f"{table} as {alias}" for table, alias in positive)
        for table, alias in negatives:
            from_sql += f" LEFT JOIN {table} as {alias} ON " + " AND ".join(inner[alias])
            _, matched_column = common.equality_keys(alias, inner[alias])[0]
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
            keys = common.equality_keys(alias, terms)
            local = [term for term in terms
                     if {a for a, _ in common.REFERENCE.findall(term)} == {alias}]
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
    keys = {alias: common.equality_keys(alias, inner[alias]) for _, alias in negatives}
    from_sql = ", ".join(f"{table} as {alias}" for table, alias in positive)
    where = " WHERE " + " AND ".join(outer) if outer else ""
    predicates = []
    for table, alias in negatives:
        pairs = keys[alias]
        left = ", ".join(column for column, _ in pairs)
        right = ", ".join(column for _, column in pairs)
        local = [term for term in inner[alias]
                 if {a for a, _ in common.REFERENCE.findall(term)} == {alias}]
        filter_sql = " WHERE " + " AND ".join(local) if local else ""
        key_aliases = {column.split(".", 1)[0] for column, _ in pairs}
        key_sources = ", ".join(
            f"{name} as {source_alias}" for name, source_alias in positive
            if source_alias in key_aliases
        )
        key_filters = [term for term in outer
                       if {a for a, _ in common.REFERENCE.findall(term)} <= key_aliases]
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


def main():
    results = {style: [] for style in ("not_exists", "not_in", "except", "left_join", "cq")}
    source_lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
    omitted = []
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    writer.writerow(("id", "source_line", "negated_count", "positive_aliases", "negated_aliases"))
    bases = {number: (query, sources, conditions)
             for number, query, sources, conditions in common.select_bases(source_lines)}
    tables = {number: {alias: table for table, alias in sources}
              for number, (_, sources, _) in bases.items()}

    def table_for(number, alias):
        return tables[number][alias]

    orders = common.balanced_sequences(
        {number: longest_sequences(sources, conditions)
         for number, (_, sources, conditions) in bases.items()},
        table_for,
    )
    for line_number, (query, sources, conditions) in bases.items():
        order = orders[line_number]
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
                    output = common.build_cq(sources, conditions, negative)
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
    print(f"Selected source queries: {len(bases)}")
    print(f"Queries per file: {len(results['cq'])}")
    print(f"Omitted further sequence levels: {len(omitted)}")
    print("Omitted IDs:", ", ".join(omitted))
    common.print_table_coverage(orders, table_for)


if __name__ == "__main__":
    main()
