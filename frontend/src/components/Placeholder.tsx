/** Placeholder until the named issue builds the real screen. */
export default function Placeholder({ name, issue, note }: { name: string; issue: string; note: string }) {
  return (
    <div className="flex min-h-full flex-col gap-3 p-6">
      <h1 className="text-2xl font-semibold">{name}</h1>
      <p className="text-unsure">Placeholder. Built in issue {issue}.</p>
      <p>{note}</p>
    </div>
  );
}
