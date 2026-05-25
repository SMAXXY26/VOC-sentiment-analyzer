export function SentimentBadge({ value }: { value: string }) {
  const styles: Record<string, string> = {
    positive: "bg-green-900 text-green-300",
    negative: "bg-red-900 text-red-300",
    neutral: "bg-gray-700 text-gray-300",
    mixed: "bg-yellow-900 text-yellow-300",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${styles[value] ?? "bg-gray-700 text-gray-300"}`}>
      {value}
    </span>
  );
}
