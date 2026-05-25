export function RiskBadge({ value }: { value: string }) {
  const styles: Record<string, string> = {
    low: "bg-green-900 text-green-300",
    medium: "bg-yellow-900 text-yellow-300",
    high: "bg-orange-900 text-orange-300",
    critical: "bg-red-900 text-red-300",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${styles[value] ?? "bg-gray-700 text-gray-300"}`}>
      {value}
    </span>
  );
}
