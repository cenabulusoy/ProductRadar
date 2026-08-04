export function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="score-row">
      <div className="score-label"><span>{label}</span><strong>{value}</strong></div>
      <div className="score-track"><div className="score-fill" style={{ width: `${value}%` }} /></div>
    </div>
  );
}
