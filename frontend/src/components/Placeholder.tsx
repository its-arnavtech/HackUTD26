import { PageTitle } from ".";

/** Placeholder until the named issue ports the real screen from the design lab. */
export default function Placeholder({ name, issue, note }: { name: string; issue: string; note: string }) {
  return (
    <div className="screen-pad">
      <PageTitle eyebrow={`Coming in ${issue}`} description={note}>
        {name}
      </PageTitle>
    </div>
  );
}
