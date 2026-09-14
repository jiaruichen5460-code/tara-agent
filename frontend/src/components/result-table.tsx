import type { ReactNode } from "react";

type ResultTableProps = {
  result: Record<string, unknown>;
};

export function ResultTable({ result }: ResultTableProps) {
  const rows = findRows(result);
  if (rows.length === 0) {
    return null;
  }
  const columns = Object.keys(rows[0]).slice(0, 8);

  return (
    <div className="table-section">
      <div className="section-heading">
        <h3>结构化结果</h3>
        <span>当前返回 {rows.length} 行</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{humanize(column)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={rowKey(row, index)}>
                {columns.map((column) => (
                  <td key={column}>{formatValue(row[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function findRows(result: Record<string, unknown>): Array<Record<string, unknown>> {
  for (const key of ["items", "asvs", "observations", "points", "sample_occurrences", "groups"]) {
    const value = result[key];
    if (Array.isArray(value) && value.every(isRecord)) {
      return value;
    }
  }
  return isRecord(result.sample) ? [result.sample] : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rowKey(row: Record<string, unknown>, index: number): string {
  const key = row.sample_id ?? row.sample_id_pangaea ?? row.amplicon;
  return typeof key === "string" ? key : String(index);
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function formatValue(value: unknown): ReactNode {
  if (value === null || value === undefined) {
    return <span className="null-value">NA</span>;
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toPrecision(5);
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
